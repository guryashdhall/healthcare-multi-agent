"""Append-only JSONL audit logger.

Audit events are deliberately PHI-free:
- raw input text is never logged (only a SHA-256 of the original bytes),
- the redactor's replacement_map is never logged,
- detected entities are summarised as counts by type, not as raw spans.

The goal is to keep enough signal for incident response and compliance review
without creating a second copy of the sensitive data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_hex(value: str) -> str:
    """Return the hex SHA-256 of the UTF-8 bytes of ``value``."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class AuditEvent:
    timestamp_utc: str
    source_file: str
    pipeline_status: str
    phi_detected_counts: dict[str, int] = field(default_factory=dict)
    deidentification_status: str = "not_run"
    phi_validation_status: str = "not_run"
    prompt_injection_status: str = "not_run"
    summarization_status: str = "not_run"
    blocked_reason: str | None = None
    raw_input_sha256: str | None = None
    deidentified_output_sha256: str | None = None
    summary_output_sha256: str | None = None
    # Optional extras used by the streaming pipeline; default-empty so the
    # CLI/sync entry point and existing tests keep producing identical events.
    safety_enabled: bool | None = None
    summarizer: str | None = None
    rehydration_placeholder_count: int | None = None
    phi_in_llm_output_counts: dict[str, int] = field(default_factory=dict)
    # Co-pilot multi-agent extension (PHI-free: statuses only, no content).
    copilot_agent_statuses: dict[str, str] = field(default_factory=dict)
    copilot_total_tokens: int | None = None
    copilot_cross_flag_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "source_file": self.source_file,
            "pipeline_status": self.pipeline_status,
            "phi_detected_counts": self.phi_detected_counts,
            "deidentification_status": self.deidentification_status,
            "phi_validation_status": self.phi_validation_status,
            "prompt_injection_status": self.prompt_injection_status,
            "summarization_status": self.summarization_status,
            "blocked_reason": self.blocked_reason,
            "raw_input_sha256": self.raw_input_sha256,
            "deidentified_output_sha256": self.deidentified_output_sha256,
            "summary_output_sha256": self.summary_output_sha256,
            "safety_enabled": self.safety_enabled,
            "summarizer": self.summarizer,
            "rehydration_placeholder_count": self.rehydration_placeholder_count,
            "phi_in_llm_output_counts": self.phi_in_llm_output_counts,
            "copilot_agent_statuses": self.copilot_agent_statuses,
            "copilot_total_tokens": self.copilot_total_tokens,
            "copilot_cross_flag_count": self.copilot_cross_flag_count,
        }


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuditLogger:
    """JSONL audit log writer."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: AuditEvent) -> None:
        """Append an audit event as a single JSON line."""
        if not event.timestamp_utc:
            event.timestamp_utc = _now_utc_iso()
        line = json.dumps(event.as_dict(), separators=(",", ":"))
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def new_event(source_file: str) -> AuditEvent:
        return AuditEvent(
            timestamp_utc=_now_utc_iso(),
            source_file=source_file,
            pipeline_status="started",
        )
