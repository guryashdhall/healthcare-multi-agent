"""FastAPI app: REST + WebSocket for the live demo."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from src.config import AUDIT_LOG_PATH, RAW_DIR, SAMPLE_NOTES
from src.pipeline import run_copilot_streaming, run_pipeline_streaming
from src.summarization.llm_summarizer import azure_openai_configured
from src.agents.copilot_runner import DISPLAY_BY_NAME, SPECIALIST_NAMES


CASES_DIR = Path(__file__).resolve().parent.parent / "data" / "cases"


REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Multi-Agent Clinical Co-Pilot")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# A small handcrafted set of metadata so the patient rail looks like an EMR
# worklist instead of a directory listing.
_NOTE_METADATA: dict[str, dict[str, Any]] = {
    "note_safe.txt": {
        "label": "Asthma · stable follow-up",
        "patient": "Anonymous · synthetic",
        "encounter": "Outpatient",
        "tag": "Already de-identified",
        "tag_color": "green",
    },
    "note_with_phi.txt": {
        "label": "COPD · acute exacerbation",
        "patient": "Sarah Mitchell · synthetic",
        "encounter": "Outpatient follow-up",
        "tag": "Contains fake PHI",
        "tag_color": "amber",
    },
    "note_with_prompt_injection.txt": {
        "label": "Hypertension · with embedded instruction",
        "patient": "Michael Thompson · synthetic",
        "encounter": "Outpatient",
        "tag": "Contains prompt-injection payload",
        "tag_color": "red",
    },
    "note_complex.txt": {
        "label": "Multi-condition · cardiology consult",
        "patient": "Eleanor Whitfield · synthetic",
        "encounter": "Outpatient · multidisciplinary",
        "tag": "Heavy PHI · multiple providers",
        "tag_color": "amber",
    },
}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "azure_openai_configured": azure_openai_configured(),
    }


@app.get("/api/cases")
async def list_cases() -> JSONResponse:
    """Structured clinical cases for the co-pilot."""
    cases: list[dict[str, Any]] = []
    if CASES_DIR.exists():
        for path in sorted(CASES_DIR.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            cases.append({
                "case_id": doc.get("case_id", path.stem),
                "label": doc.get("label", path.stem),
                "subtitle": doc.get("subtitle", ""),
                "tag": doc.get("tag", ""),
                "tag_color": doc.get("tag_color", "neutral"),
                "presenting_complaint": doc.get("presenting_complaint", ""),
                "case": doc,
            })
    return JSONResponse({
        "cases": cases,
        "specialists": [
            {"name": n, **DISPLAY_BY_NAME.get(n, {"display": n, "icon": "?"})}
            for n in SPECIALIST_NAMES
        ],
        "orchestrator": {"name": "orchestrator", **DISPLAY_BY_NAME.get("orchestrator", {"display": "Orchestrator", "icon": "ORC"})},
    })


@app.get("/api/notes")
async def list_notes() -> JSONResponse:
    """Return the preset notes for the patient rail."""
    notes = []
    for name in SAMPLE_NOTES:
        path = RAW_DIR / name
        if not path.exists():
            continue
        meta = _NOTE_METADATA.get(name, {})
        notes.append(
            {
                "id": name,
                "label": meta.get("label", name),
                "patient": meta.get("patient", "Synthetic"),
                "encounter": meta.get("encounter", "Outpatient"),
                "tag": meta.get("tag", ""),
                "tag_color": meta.get("tag_color", "neutral"),
                "preview": path.read_text(encoding="utf-8")[:240],
                "text": path.read_text(encoding="utf-8"),
            }
        )
    return JSONResponse({"notes": notes})


# Tell every browser to re-fetch this endpoint every time. Without this the
# UI's Refresh button can serve a stale cached response after a new run.
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/api/audit")
async def get_audit() -> JSONResponse:
    """Return the audit log lines + the no-raw-PHI assertion result."""
    if not AUDIT_LOG_PATH.exists():
        return JSONResponse(
            {"events": [], "phi_check": {"passed": True, "scanned_strings": 0}},
            headers=_NO_CACHE_HEADERS,
        )
    events: list[dict[str, Any]] = []
    contents = AUDIT_LOG_PATH.read_text(encoding="utf-8")
    for line in contents.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    phi_strings = _read_known_phi_strings()
    leaked = sorted({s for s in phi_strings if s in contents})
    return JSONResponse(
        {
            "events": events,
            "phi_check": {
                "passed": not leaked,
                "scanned_strings": len(phi_strings),
                "leaked": leaked,
            },
        },
        headers=_NO_CACHE_HEADERS,
    )


def _read_known_phi_strings() -> list[str]:
    """Pull the obvious raw-PHI strings out of the synthetic inputs for the
    audit-log assertion. Covers both raw text notes and structured case JSONs
    so the assertion is meaningful for every demo path."""
    needles: set[str] = set()

    # 1) Raw text notes in data/raw/*.txt
    for name in SAMPLE_NOTES:
        path = RAW_DIR / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            for prefix in (
                "Patient:",
                "Provider:",
                "Email:",
                "Phone:",
                "MRN:",
                "Health Card:",
                "Address:",
            ):
                if line.startswith(prefix):
                    val = line[len(prefix) :].strip()
                    if val:
                        needles.add(val)

    # 2) Structured cases in data/cases/*.json. The case files carry their
    # PHI in well-known fields; pull them so a leak via Whitfield/Chen/Singh/
    # Patel is also caught even though those patients don't have raw .txt notes.
    if CASES_DIR.exists():
        for path in sorted(CASES_DIR.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            demo = doc.get("demographics") or {}
            for field in ("patient_name", "mrn", "phone", "address", "dob"):
                val = demo.get(field)
                if isinstance(val, str) and val.strip():
                    needles.add(val.strip())
            # Pull provider names out of medication entries and the clinician's
            # plan if present.
            for med in doc.get("current_medications") or []:
                for k in ("prescriber", "provider"):
                    val = (med or {}).get(k)
                    if isinstance(val, str) and val.strip():
                        needles.add(val.strip())

    return [n for n in needles if len(n) >= 5]


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket) -> None:
    await ws.accept()

    # Track whether the WS is alive. If a send fails (typically because the
    # browser tab was backgrounded long enough for the socket to die), set
    # this so the run aborts instead of burning compute that nobody sees.
    ws_alive = {"open": True}

    # Drain any heartbeat/ping messages the client sends so its keep-alive
    # timer doesn't pile up unread payloads in the receive queue.
    async def _drain_client_messages() -> None:
        while ws_alive["open"]:
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect:
                ws_alive["open"] = False
                return
            except Exception:
                ws_alive["open"] = False
                return
            if isinstance(msg, dict) and msg.get("type") == "ping":
                try:
                    await ws.send_json({"type": "pong", "data": {"ts": msg.get("ts")}})
                except Exception:
                    ws_alive["open"] = False
                    return

    drain_task: asyncio.Task | None = None

    try:
        request = await ws.receive_json()
        mode: str = request.get("mode", "summary")  # "summary" | "copilot"

        # Start the drain loop only AFTER we've consumed the initial request
        # payload, so we don't race with it.
        drain_task = asyncio.create_task(_drain_client_messages())

        async def callback(event: dict[str, Any]) -> None:
            if not ws_alive["open"]:
                return
            try:
                await ws.send_json(event)
            except Exception:
                # Mark the connection dead so the rest of the run stops
                # emitting and the agent fan-out short-circuits next tick.
                ws_alive["open"] = False

        if mode == "copilot":
            case_id: str = request.get("case_id") or "audience_paste"
            case_json: dict[str, Any] = request.get("case_json") or {}
            engine: str = request.get("engine", "azure_openai")
            if engine not in ("azure_openai", "simulated"):
                engine = "azure_openai"
            if not case_json:
                await ws.send_json(
                    {"type": "error", "data": {"message": "Empty case payload"}}
                )
                await ws.close()
                return
            await run_copilot_streaming(
                case_id=case_id,
                case_json=case_json,
                engine=engine,
                event_callback=callback,
            )
        else:
            text: str = request.get("text") or ""
            source_label: str = request.get("source_label") or "audience_paste"
            safety_enabled: bool = bool(request.get("safety_enabled", True))
            summarizer: str = request.get("summarizer", "azure_openai")
            if summarizer not in ("local", "azure_openai", "simulated"):
                summarizer = "azure_openai"
            if not text.strip():
                await ws.send_json(
                    {"type": "error", "data": {"message": "Empty note"}}
                )
                await ws.close()
                return
            await run_pipeline_streaming(
                text=text,
                source_label=source_label,
                safety_enabled=safety_enabled,
                summarizer=summarizer,  # type: ignore[arg-type]
                event_callback=callback,
            )
    except WebSocketDisconnect:
        ws_alive["open"] = False
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "data": {
                        "message": f"{type(exc).__name__}: {exc}",
                    },
                }
            )
        except Exception:
            pass
    finally:
        ws_alive["open"] = False
        if drain_task is not None:
            drain_task.cancel()
        try:
            await asyncio.sleep(0)
            await ws.close()
        except Exception:
            pass
