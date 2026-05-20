"""Plain-text console renderer for pipeline results.

Uses only the standard library so it runs anywhere; ``rich`` is optional and
not required for the demo to look clean.
"""

from __future__ import annotations

import json
from typing import Any

from ..pipeline import PipelineResult

PASS = "[PASS]"
BLOCK = "[BLOCKED]"
WARN = "[WARN]"

# Unicode symbols used when stdout supports them.
_UNICODE = {
    PASS: "\u2705",  # white heavy check mark
    BLOCK: "\u274c",  # cross mark
    WARN: "\u26a0\ufe0f",  # warning sign
}


def _sym(label: str, unicode_ok: bool) -> str:
    return _UNICODE[label] if unicode_ok else label


def _supports_unicode() -> bool:
    import sys

    enc = (sys.stdout.encoding or "").lower()
    return "utf" in enc


def _fmt_status(passed: bool, *, unicode_ok: bool) -> str:
    return _sym(PASS, unicode_ok) + " passed" if passed else _sym(BLOCK, unicode_ok) + " failed"


def _truncate(value: str, limit: int = 90) -> str:
    value = value.replace("\n", " ").strip()
    return value if len(value) <= limit else value[: limit - 3] + "..."


def render_result(result: PipelineResult) -> str:
    unicode_ok = _supports_unicode()
    lines: list[str] = []

    lines.append("=" * 78)
    lines.append(f"File: {result.source_file}")
    lines.append("-" * 78)

    if result.phi_detected_counts:
        counts = ", ".join(
            f"{k}={v}" for k, v in sorted(result.phi_detected_counts.items())
        )
    else:
        counts = "none"
    lines.append(f"PHI detected             : {counts}")

    lines.append(
        "De-identification        : "
        + (_sym(PASS, unicode_ok) + " completed")
    )

    lines.append(
        "PHI leakage validation   : "
        + _fmt_status(result.validation_result.get("passed", False), unicode_ok=unicode_ok)
    )
    if not result.validation_result.get("passed", True):
        leak_cats = sorted({
            f["category"] for f in result.validation_result.get("leakage_findings", [])
        })
        lines.append(f"  -> categories: {', '.join(leak_cats)}")

    lines.append(
        "Prompt injection check   : "
        + _fmt_status(
            result.prompt_injection_result.get("passed", False),
            unicode_ok=unicode_ok,
        )
    )
    if not result.prompt_injection_result.get("passed", True):
        patterns = sorted({
            f["pattern"] for f in result.prompt_injection_result.get("findings", [])
        })
        lines.append(f"  -> patterns: {', '.join(patterns)}")

    if result.status == "completed":
        lines.append(
            "Summarization            : " + _sym(PASS, unicode_ok) + " completed"
        )
    else:
        lines.append(
            "Summarization            : " + _sym(BLOCK, unicode_ok) + " blocked"
        )
        lines.append(f"Blocked reason           : {result.blocked_reason}")

    if result.deidentified_text_path:
        lines.append(f"De-identified text path  : {result.deidentified_text_path}")
    if result.summary_path:
        lines.append(f"Summary path             : {result.summary_path}")

    if result.status == "completed" and result.summary is not None:
        lines.append("")
        lines.append("Safe summary preview (de-identified, structured JSON):")
        preview = _summary_preview(result.summary)
        for line in preview.splitlines():
            lines.append("  " + line)

    return "\n".join(lines)


def _summary_preview(summary: dict[str, Any]) -> str:
    """Render a compact preview of the structured summary."""
    keys = [
        "summary_type",
        "chief_concern",
        "relevant_history",
        "medications_mentioned",
        "risk_flags",
        "follow_up_questions",
        "source_text_status",
        "disclaimer",
    ]
    preview = {k: summary[k] for k in keys if k in summary}
    return json.dumps(preview, indent=2)


def render_header(unicode_ok: bool | None = None) -> str:
    if unicode_ok is None:
        unicode_ok = _supports_unicode()
    title = "Claude Code for Healthcare: PHI-Safe AI Pipeline Demo"
    bar = "#" * 78
    sub = (
        "Synthetic data only. Demonstration of privacy-preserving engineering "
        "patterns. Not a HIPAA/PHIPA-compliant system."
    )
    return f"{bar}\n{title}\n{sub}\n{bar}"


def render_footer(unicode_ok: bool | None = None) -> str:
    if unicode_ok is None:
        unicode_ok = _supports_unicode()
    line = (
        "Key lesson: In healthcare AI, the model is not the first step. "
        "The privacy and safety gate is."
    )
    bar = "#" * 78
    return f"{bar}\n{line}\n{bar}"
