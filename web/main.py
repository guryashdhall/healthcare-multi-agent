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

from src.config import AUDIT_LOG_PATH, DEMO_NOTES, RAW_DIR
from src.pipeline import run_copilot_streaming, run_pipeline_streaming
from src.summarization.llm_summarizer import azure_openai_configured
from src.agents.copilot_runner import DISPLAY_BY_NAME, SPECIALIST_NAMES


CASES_DIR = Path(__file__).resolve().parent.parent / "data" / "cases"


REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Claude Code for Healthcare: PHI-Safe Pipeline Demo")
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
    for name in DEMO_NOTES:
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


@app.get("/api/audit")
async def get_audit() -> JSONResponse:
    """Return the audit log lines + the no-raw-PHI assertion result."""
    if not AUDIT_LOG_PATH.exists():
        return JSONResponse(
            {"events": [], "phi_check": {"passed": True, "scanned_strings": 0}}
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
        }
    )


def _read_known_phi_strings() -> list[str]:
    """Pull the obvious raw-PHI strings out of the synthetic notes for the
    audit-log assertion."""
    needles: set[str] = set()
    for name in DEMO_NOTES:
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
    return [n for n in needles if len(n) >= 5]


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket) -> None:
    await ws.accept()
    try:
        request = await ws.receive_json()
        mode: str = request.get("mode", "summary")  # "summary" | "copilot"

        async def callback(event: dict[str, Any]) -> None:
            try:
                await ws.send_json(event)
            except Exception:
                pass

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
        try:
            await asyncio.sleep(0)
            await ws.close()
        except Exception:
            pass
