"""End-to-end PHI-safe summarization pipeline.

The pipeline is intentionally fail-closed: if any safety gate is unsure or
fails, summarization is blocked and an audit record is written.

Two entry points:
- ``run_pipeline``           sync, used by the CLI demo and tests.
- ``run_pipeline_streaming`` async, used by the FastAPI WebSocket endpoint;
                             emits per-stage events for the live UI.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional

from .audit.audit_logger import AuditEvent, AuditLogger, sha256_hex
from .config import AUDIT_LOG_PATH, PROCESSED_DIR, RAW_DIR
from .deid.detector import detect_phi
from .deid.redactor import RedactionResult, redact
from .deid.rehydrator import rehydrate
from .summarization.safe_summarizer import summarize_safely
from .validation.phi_leakage_checker import LeakageResult, check_phi_leakage
from .validation.prompt_injection_checker import (
    InjectionResult,
    check_prompt_injection,
)
from .agents import copilot_runner
from .deid.structured_redactor import redact_case_structured


EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
SummarizerName = Literal["local", "azure_openai", "simulated"]


@dataclass
class PipelineResult:
    source_file: str
    status: str  # "completed" or "blocked"
    blocked_reason: str | None = None
    phi_detected_counts: dict[str, int] = field(default_factory=dict)
    validation_result: dict[str, Any] = field(default_factory=dict)
    prompt_injection_result: dict[str, Any] = field(default_factory=dict)
    deidentified_text_path: str | None = None
    summary_path: str | None = None
    audit_written: bool = False
    summary: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "status": self.status,
            "blocked_reason": self.blocked_reason,
            "phi_detected_counts": self.phi_detected_counts,
            "validation_result": self.validation_result,
            "prompt_injection_result": self.prompt_injection_result,
            "deidentified_text_path": self.deidentified_text_path,
            "summary_path": self.summary_path,
            "audit_written": self.audit_written,
        }


def _processed_paths(source_file: str) -> tuple[Path, Path]:
    stem = Path(source_file).stem
    deid_path = PROCESSED_DIR / f"{stem}.deidentified.txt"
    summary_path = PROCESSED_DIR / f"{stem}.summary.json"
    return deid_path, summary_path


def _build_blocked_reason(
    leakage: LeakageResult, injection: InjectionResult
) -> str | None:
    reasons: list[str] = []
    if not injection.passed:
        labels = sorted({f.pattern for f in injection.findings})
        reasons.append("prompt_injection_detected:" + ",".join(labels))
    if not leakage.passed:
        labels = sorted({f.category for f in leakage.leakage_findings})
        reasons.append("phi_leakage_detected:" + ",".join(labels))
    return "; ".join(reasons) if reasons else None


def run_pipeline(
    source_file: str,
    *,
    raw_dir: Path | None = None,
    audit_log_path: Path | None = None,
    write_outputs: bool = True,
) -> PipelineResult:
    """Run the full pipeline against a single note file.

    ``source_file`` is just the file name; it is resolved against ``raw_dir``
    (defaults to the repo's data/raw folder).
    """
    raw_dir = Path(raw_dir) if raw_dir is not None else RAW_DIR
    audit_log_path = (
        Path(audit_log_path) if audit_log_path is not None else AUDIT_LOG_PATH
    )

    audit = AuditLogger(audit_log_path)
    event: AuditEvent = AuditLogger.new_event(source_file)

    raw_path = raw_dir / source_file
    raw_text = raw_path.read_text(encoding="utf-8")
    event.raw_input_sha256 = sha256_hex(raw_text)

    # 1) Prompt injection runs against raw text - the raw note is the threat
    # surface and we want to catch malicious instructions before they have a
    # chance to influence anything downstream.
    injection_result = check_prompt_injection(raw_text)
    event.prompt_injection_status = "passed" if injection_result.passed else "failed"

    # 2) Detect and redact PHI.
    entities = detect_phi(raw_text)
    redaction = redact(raw_text, entities)
    event.phi_detected_counts = redaction.entity_counts
    event.deidentification_status = "completed"

    # 3) Validate that the redacted text no longer contains obvious PHI.
    leakage_result = check_phi_leakage(redaction.deidentified_text)
    event.phi_validation_status = "passed" if leakage_result.passed else "failed"

    # 4) Decide. Fail-closed: any failure blocks summarization.
    blocked_reason = _build_blocked_reason(leakage_result, injection_result)
    deid_text_path: Path | None = None
    summary_path: Path | None = None
    summary: dict[str, Any] | None = None

    if write_outputs:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if blocked_reason is None:
        # 5) Safe path: write de-identified text, summarise, write summary.
        if write_outputs:
            deid_text_path, summary_path = _processed_paths(source_file)
            deid_text_path.write_text(
                redaction.deidentified_text, encoding="utf-8"
            )
        event.deidentified_output_sha256 = sha256_hex(redaction.deidentified_text)

        summary = summarize_safely(redaction.deidentified_text)
        summary_json = json.dumps(summary, indent=2)
        event.summary_output_sha256 = sha256_hex(summary_json)
        event.summarization_status = "completed"
        event.pipeline_status = "completed"
        if write_outputs and summary_path is not None:
            summary_path.write_text(summary_json, encoding="utf-8")
    else:
        event.summarization_status = "blocked"
        event.pipeline_status = "blocked"
        event.blocked_reason = blocked_reason

    audit.write(event)

    return PipelineResult(
        source_file=source_file,
        status=event.pipeline_status,
        blocked_reason=blocked_reason,
        phi_detected_counts=redaction.entity_counts,
        validation_result=leakage_result.as_dict(),
        prompt_injection_result=injection_result.as_dict(),
        deidentified_text_path=str(deid_text_path) if deid_text_path else None,
        summary_path=str(summary_path) if summary_path else None,
        audit_written=True,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Streaming pipeline (used by the FastAPI WebSocket endpoint)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def _emit(callback: Optional[EventCallback], event: dict[str, Any]) -> None:
    if callback is None:
        return
    event.setdefault("ts", _now_iso())
    await callback(event)


async def run_pipeline_streaming(
    *,
    text: str,
    source_label: str,
    safety_enabled: bool = True,
    summarizer: SummarizerName = "azure_openai",
    event_callback: Optional[EventCallback] = None,
    audit_log_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Run the pipeline against ``text`` while emitting live UI events.

    Returns a final result dict mirroring the last ``done`` event's payload.
    """
    audit_log_path = (
        Path(audit_log_path) if audit_log_path is not None else AUDIT_LOG_PATH
    )
    audit = AuditLogger(audit_log_path)
    event = AuditLogger.new_event(source_label)
    event.raw_input_sha256 = sha256_hex(text)
    event.safety_enabled = safety_enabled
    event.summarizer = summarizer

    started = time.monotonic()
    await _emit(
        event_callback,
        {
            "type": "run_started",
            "data": {
                "source_label": source_label,
                "safety_enabled": safety_enabled,
                "summarizer": summarizer,
            },
        },
    )

    if not safety_enabled:
        return await _run_unsafe_demo(
            text=text,
            source_label=source_label,
            event_callback=event_callback,
            audit=audit,
            event=event,
            started=started,
            summarizer=summarizer,
        )

    return await _run_safe(
        text=text,
        source_label=source_label,
        event_callback=event_callback,
        audit=audit,
        event=event,
        started=started,
        summarizer=summarizer,
    )


async def _run_safe(
    *,
    text: str,
    source_label: str,
    event_callback: Optional[EventCallback],
    audit: AuditLogger,
    event: AuditEvent,
    started: float,
    summarizer: SummarizerName,
) -> dict[str, Any]:
    # Stage 1: prompt injection check on raw text.
    await _emit(event_callback, {"type": "stage_start", "stage": "prompt_injection"})
    injection_result = check_prompt_injection(text)
    event.prompt_injection_status = "passed" if injection_result.passed else "failed"
    await _emit(
        event_callback,
        {
            "type": "stage_end",
            "stage": "prompt_injection",
            "status": event.prompt_injection_status,
            "data": {
                "patterns": sorted({f.pattern for f in injection_result.findings}),
                "findings": [f.as_dict() for f in injection_result.findings],
            },
        },
    )

    # Stage 2: PHI detection.
    await _emit(event_callback, {"type": "stage_start", "stage": "phi_detection"})
    entities = detect_phi(text)
    await _emit(
        event_callback,
        {
            "type": "stage_end",
            "stage": "phi_detection",
            "status": "completed",
            "data": {
                "entities": [e.as_dict() for e in entities],
                "counts": {k: v for k, v in _count_by_type(entities).items()},
            },
        },
    )

    # Stage 3: redaction.
    await _emit(event_callback, {"type": "stage_start", "stage": "redaction"})
    redaction = redact(text, entities)
    event.phi_detected_counts = redaction.entity_counts
    event.deidentification_status = "completed"
    event.deidentified_output_sha256 = sha256_hex(redaction.deidentified_text)
    await _emit(
        event_callback,
        {
            "type": "stage_end",
            "stage": "redaction",
            "status": "completed",
            "data": {
                "deidentified_text": redaction.deidentified_text,
                "entity_counts": redaction.entity_counts,
                # NOTE: replacement_map is sensitive - never sent.
            },
        },
    )

    # Stage 4: PHI leakage validation on the redacted text.
    await _emit(event_callback, {"type": "stage_start", "stage": "phi_leakage"})
    leakage_result = check_phi_leakage(redaction.deidentified_text)
    event.phi_validation_status = "passed" if leakage_result.passed else "failed"
    await _emit(
        event_callback,
        {
            "type": "stage_end",
            "stage": "phi_leakage",
            "status": event.phi_validation_status,
            "data": leakage_result.as_dict(),
        },
    )

    # Decide.
    blocked_reason = _build_blocked_reason(leakage_result, injection_result)
    if blocked_reason is not None:
        event.summarization_status = "blocked"
        event.pipeline_status = "blocked"
        event.blocked_reason = blocked_reason
        await _emit(
            event_callback,
            {
                "type": "blocked",
                "data": {
                    "reason": blocked_reason,
                    "injection_passed": injection_result.passed,
                    "leakage_passed": leakage_result.passed,
                },
            },
        )
        audit.write(event)
        await _emit(
            event_callback,
            {"type": "audit_written", "data": {"event": event.as_dict()}},
        )
        result = {
            "status": "blocked",
            "blocked_reason": blocked_reason,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        await _emit(event_callback, {"type": "done", "data": result})
        return result

    # Stage 5: LLM summarization (de-identified text only).
    await _emit(
        event_callback,
        {"type": "stage_start", "stage": "summarization", "data": {"engine": summarizer}},
    )
    llm_result = await _summarize(
        redaction.deidentified_text,
        summarizer=summarizer,
        event_callback=event_callback,
        safety_enabled=True,
    )
    event.summarization_status = "completed"
    summary_json = json.dumps(llm_result["summary"], indent=2)
    event.summary_output_sha256 = sha256_hex(summary_json)
    await _emit(
        event_callback,
        {
            "type": "summary_final",
            "data": {
                "summary": llm_result["summary"],
                "summary_source": llm_result["summary_source"],
                "error": llm_result.get("error"),
            },
        },
    )
    await _emit(
        event_callback,
        {"type": "stage_end", "stage": "summarization", "status": "completed"},
    )

    # Stage 6: re-hydration (server-side trusted re-identification).
    await _emit(event_callback, {"type": "stage_start", "stage": "rehydration"})
    rehydrated = rehydrate(llm_result["summary"], redaction.replacement_map)
    placeholder_total = sum(rehydrated.placeholders_replaced.values())
    event.rehydration_placeholder_count = placeholder_total
    await _emit(
        event_callback,
        {
            "type": "rehydration",
            "data": {
                "rehydrated_summary": rehydrated.rehydrated_summary,
                "placeholders_replaced": rehydrated.placeholders_replaced,
                "unresolved_placeholders": rehydrated.unresolved_placeholders,
            },
        },
    )
    await _emit(
        event_callback,
        {
            "type": "stage_end",
            "stage": "rehydration",
            "status": "completed",
            "data": {"placeholders_replaced_total": placeholder_total},
        },
    )

    # Stage 7: audit.
    await _emit(event_callback, {"type": "stage_start", "stage": "audit"})
    event.pipeline_status = "completed"
    audit.write(event)
    await _emit(
        event_callback,
        {"type": "audit_written", "data": {"event": event.as_dict()}},
    )
    await _emit(
        event_callback,
        {"type": "stage_end", "stage": "audit", "status": "completed"},
    )

    result = {
        "status": "completed",
        "summary_source": llm_result["summary_source"],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    await _emit(event_callback, {"type": "done", "data": result})
    return result


async def _run_unsafe_demo(
    *,
    text: str,
    source_label: str,
    event_callback: Optional[EventCallback],
    audit: AuditLogger,
    event: AuditEvent,
    started: float,
    summarizer: SummarizerName,
) -> dict[str, Any]:
    """Danger-toggle path: send raw text directly to the LLM.

    Synthetic data only - this exists to make the value of the safety gate
    visible to the audience. The LLM output is post-scanned for raw PHI so
    the UI can show what leaked.
    """
    await _emit(
        event_callback,
        {
            "type": "mode_unsafe_demo",
            "data": {
                "warning": (
                    "DANGER MODE: safety gate disabled. Raw note will be "
                    "sent to the LLM. Synthetic data only."
                )
            },
        },
    )
    event.deidentification_status = "skipped"
    event.phi_validation_status = "skipped"
    event.prompt_injection_status = "skipped"

    await _emit(
        event_callback,
        {"type": "stage_start", "stage": "summarization", "data": {"engine": summarizer}},
    )
    llm_result = await _summarize(
        text,
        summarizer=summarizer,
        event_callback=event_callback,
        safety_enabled=False,
    )
    summary_json = json.dumps(llm_result["summary"], indent=2)
    event.summary_output_sha256 = sha256_hex(summary_json)
    event.summarization_status = "completed"
    event.pipeline_status = "unsafe_demo_completed"
    await _emit(
        event_callback,
        {
            "type": "summary_final",
            "data": {
                "summary": llm_result["summary"],
                "summary_source": llm_result["summary_source"],
                "error": llm_result.get("error"),
            },
        },
    )
    await _emit(
        event_callback,
        {"type": "stage_end", "stage": "summarization", "status": "completed"},
    )

    # Post-scan the LLM output to show the audience what leaked.
    leaked_entities = detect_phi(json.dumps(llm_result["summary"]))
    leaked_counts = _count_by_type(leaked_entities)
    event.phi_in_llm_output_counts = leaked_counts
    await _emit(
        event_callback,
        {
            "type": "unsafe_phi_leak_scan",
            "data": {
                "phi_in_llm_output_counts": leaked_counts,
                "examples": [e.as_dict() for e in leaked_entities[:10]],
            },
        },
    )

    audit.write(event)
    await _emit(
        event_callback,
        {"type": "audit_written", "data": {"event": event.as_dict()}},
    )

    result = {
        "status": "unsafe_demo_completed",
        "phi_in_llm_output_counts": leaked_counts,
        "summary_source": llm_result["summary_source"],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    await _emit(event_callback, {"type": "done", "data": result})
    return result


async def _summarize(
    text: str,
    *,
    summarizer: SummarizerName,
    event_callback: Optional[EventCallback],
    safety_enabled: bool = True,
) -> dict[str, Any]:
    """Run the chosen summarizer and return a uniform dict."""
    if summarizer == "local":
        summary = summarize_safely(text)
        return {
            "summary": summary,
            "summary_source": "local",
            "error": None,
        }

    async def on_token(piece: str) -> None:
        if event_callback is not None:
            await event_callback(
                {"type": "summary_token", "ts": _now_iso(), "data": {"delta": piece}}
            )

    if summarizer == "simulated":
        from .summarization.simulated_llm import stream_simulated

        summary = await stream_simulated(
            text, safety_enabled=safety_enabled, on_token=on_token
        )
        return {
            "summary": summary,
            "summary_source": "simulated_offline",
            "error": None,
        }

    # Lazy import so the openai SDK is optional for the CLI/tests.
    from .summarization.llm_summarizer import stream_summary

    llm = await stream_summary(text, on_token=on_token)
    return {
        "summary": llm.summary,
        "summary_source": llm.summary_source,
        "error": llm.error,
    }


def _count_by_type(entities) -> dict[str, int]:  # local helper to avoid extra import
    counts: dict[str, int] = {}
    for e in entities:
        counts[e.entity_type] = counts.get(e.entity_type, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Co-pilot streaming pipeline (FastAPI WebSocket endpoint, /ws/run mode=copilot)
# ---------------------------------------------------------------------------


async def run_copilot_streaming(
    *,
    case_id: str,
    case_json: dict[str, Any],
    engine: str = "azure_openai",
    event_callback: Optional[EventCallback] = None,
    audit_log_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Run the multi-agent clinical co-pilot on a structured case.

    The PHI-safe pipeline runs first against the case serialized as text.
    If safe, fan out to all six specialists in parallel via the agent runner,
    then the orchestrator. Final clinician-facing payload is re-hydrated
    server-side.
    """
    audit_log_path = (
        Path(audit_log_path) if audit_log_path is not None else AUDIT_LOG_PATH
    )
    audit = AuditLogger(audit_log_path)
    event = AuditLogger.new_event(case_id)
    event.summarizer = f"copilot/{engine}"
    event.safety_enabled = True

    raw_text = json.dumps(case_json, indent=2)
    event.raw_input_sha256 = sha256_hex(raw_text)

    started = time.monotonic()
    await _emit(event_callback, {"type": "run_started", "data": {
        "mode": "copilot",
        "case_id": case_id,
        "engine": engine,
    }})

    # 1) Prompt injection on the raw case text (defensive even though cases
    # are committed locally).
    await _emit(event_callback, {"type": "stage_start", "stage": "prompt_injection"})
    injection_result = check_prompt_injection(raw_text)
    event.prompt_injection_status = "passed" if injection_result.passed else "failed"
    await _emit(event_callback, {
        "type": "stage_end",
        "stage": "prompt_injection",
        "status": event.prompt_injection_status,
        "data": {
            "patterns": sorted({f.pattern for f in injection_result.findings}),
            "findings": [f.as_dict() for f in injection_result.findings],
        },
    })

    # 2) Structured redaction of the case dict's known PHI fields
    # (demographics + any "Dr. X Y" substrings everywhere). Builds a primary
    # replacement_map keyed by raw surface strings.
    await _emit(event_callback, {"type": "stage_start", "stage": "phi_detection"})
    deid_case_dict, struct_map = redact_case_structured(case_json)
    deid_serialized = json.dumps(deid_case_dict, indent=2)

    # 3) Run the free-text detector over the serialized de-identified text to
    # catch any residual PHI in narrative fields (clinician's plan, history
    # free-text, etc.). Anything new gets a fresh placeholder.
    residual_entities = detect_phi(deid_serialized)
    redaction = redact(deid_serialized, residual_entities)

    # Merge the structured map and the free-text map. The structured map is
    # primary - its placeholders are already in place.
    combined_map: dict[str, str] = dict(struct_map)
    combined_map.update(redaction.replacement_map)

    combined_counts: dict[str, int] = dict(redaction.entity_counts)
    # Approximate counts from the structured pass too.
    for raw, placeholder in struct_map.items():
        # placeholder looks like [TYPE_N]
        try:
            entity_type = placeholder[1:placeholder.rindex("_")]
        except ValueError:
            continue
        combined_counts[entity_type] = combined_counts.get(entity_type, 0) + 1

    event.phi_detected_counts = combined_counts
    await _emit(event_callback, {
        "type": "stage_end",
        "stage": "phi_detection",
        "status": "completed",
        "data": {
            "counts": combined_counts,
            "entities": [e.as_dict() for e in residual_entities],
        },
    })

    # 4) Redaction stage event - report the final deidentified text the
    # agents will receive.
    await _emit(event_callback, {"type": "stage_start", "stage": "redaction"})
    event.deidentification_status = "completed"
    event.deidentified_output_sha256 = sha256_hex(redaction.deidentified_text)
    # Replace the redactor's replacement_map with the merged map so the
    # downstream rehydrator has full coverage.
    redaction.replacement_map = combined_map
    await _emit(event_callback, {
        "type": "stage_end",
        "stage": "redaction",
        "status": "completed",
        "data": {
            "deidentified_text": redaction.deidentified_text,
            "entity_counts": combined_counts,
        },
    })

    # 4) Validate no PHI leakage remains.
    await _emit(event_callback, {"type": "stage_start", "stage": "phi_leakage"})
    leakage_result = check_phi_leakage(redaction.deidentified_text)
    event.phi_validation_status = "passed" if leakage_result.passed else "failed"
    await _emit(event_callback, {
        "type": "stage_end",
        "stage": "phi_leakage",
        "status": event.phi_validation_status,
        "data": leakage_result.as_dict(),
    })

    blocked_reason = _build_blocked_reason(leakage_result, injection_result)
    if blocked_reason is not None:
        event.summarization_status = "blocked"
        event.pipeline_status = "blocked"
        event.blocked_reason = blocked_reason
        await _emit(event_callback, {
            "type": "blocked",
            "data": {"reason": blocked_reason},
        })
        audit.write(event)
        await _emit(event_callback, {
            "type": "audit_written",
            "data": {"event": event.as_dict()},
        })
        result = {
            "status": "blocked",
            "blocked_reason": blocked_reason,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        await _emit(event_callback, {"type": "done", "data": result})
        return result

    # 5) Fan out to the six specialists + orchestrator. The agents only see
    # the de-identified case text.
    await _emit(event_callback, {"type": "stage_start", "stage": "copilot"})
    agent_results = await copilot_runner.run_all(
        case_id=case_id,
        deidentified_case_json=redaction.deidentified_text,
        engine=engine,
        emit=event_callback,
    )
    statuses = {
        name: (r.error or r.source) if r.error else "ok"
        for name, r in agent_results.items()
    }
    event.copilot_agent_statuses = statuses

    # Approximate "total tokens" by raw-text length per agent (we don't get
    # exact token counts back from the streamed API).
    event.copilot_total_tokens = sum(
        max(1, len(r.raw_text) // 4) for r in agent_results.values()
    )

    orchestrator_output = agent_results.get("orchestrator")
    cross_flags = []
    if orchestrator_output and orchestrator_output.output:
        cross_flags = orchestrator_output.output.get("cross_flags", [])
    event.copilot_cross_flag_count = len(cross_flags)

    await _emit(event_callback, {
        "type": "stage_end",
        "stage": "copilot",
        "status": "completed",
        "data": {"agent_statuses": statuses, "cross_flag_count": event.copilot_cross_flag_count},
    })

    # 6) Re-hydrate the orchestrator's final summary + any placeholder-using
    # text in the specialist outputs the UI will display to the clinician.
    if orchestrator_output and orchestrator_output.output:
        rehydrated = rehydrate(orchestrator_output.output, redaction.replacement_map)
        event.rehydration_placeholder_count = sum(
            rehydrated.placeholders_replaced.values()
        )
        await _emit(event_callback, {
            "type": "rehydration",
            "data": {
                "rehydrated_orchestrator": rehydrated.rehydrated_summary,
                "placeholders_replaced": rehydrated.placeholders_replaced,
                "unresolved_placeholders": rehydrated.unresolved_placeholders,
            },
        })

    # 7) Audit.
    event.summarization_status = "completed"
    event.pipeline_status = "completed"
    audit.write(event)
    await _emit(event_callback, {
        "type": "audit_written",
        "data": {"event": event.as_dict()},
    })

    final = {
        "status": "completed",
        "agent_count": len(agent_results),
        "cross_flag_count": event.copilot_cross_flag_count,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    await _emit(event_callback, {"type": "done", "data": final})
    return final
