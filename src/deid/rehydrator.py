"""Server-side re-identification of de-identified summaries.

This is the **trusted** half of the redact-summarize-rehydrate pattern. It
takes a structured summary that the LLM produced (which only contains
placeholders such as ``[PATIENT_NAME_1]``) plus the in-memory
``replacement_map`` from the redaction step, and substitutes placeholders
back to their original values so the clinician sees a usable summary.

Trust boundary:
- ``replacement_map`` lives only inside the app process.
- It is NEVER sent to the LLM.
- It is NEVER written to the audit log.
- Only the COUNT of placeholders re-hydrated is recorded for audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")


@dataclass
class RehydrationResult:
    rehydrated_summary: dict[str, Any]
    placeholders_replaced: dict[str, int] = field(default_factory=dict)
    unresolved_placeholders: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rehydrated_summary": self.rehydrated_summary,
            "placeholders_replaced": self.placeholders_replaced,
            "unresolved_placeholders": self.unresolved_placeholders,
        }


def _invert_replacement_map(replacement_map: dict[str, str]) -> dict[str, str]:
    """Build a {placeholder: original_phi} lookup."""
    return {placeholder: original for original, placeholder in replacement_map.items()}


def _rehydrate_string(
    text: str,
    placeholder_to_original: dict[str, str],
    replaced_counts: dict[str, int],
    unresolved: list[str],
) -> str:
    """Substitute placeholders inside a single string."""

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        key = token[1:-1]  # strip [ ]
        if token in placeholder_to_original:
            replaced_counts[key] = replaced_counts.get(key, 0) + 1
            return placeholder_to_original[token]
        if key not in unresolved:
            unresolved.append(key)
        return token

    return _PLACEHOLDER_RE.sub(repl, text)


def _walk(
    value: Any,
    placeholder_to_original: dict[str, str],
    replaced_counts: dict[str, int],
    unresolved: list[str],
) -> Any:
    if isinstance(value, str):
        return _rehydrate_string(
            value, placeholder_to_original, replaced_counts, unresolved
        )
    if isinstance(value, list):
        return [
            _walk(item, placeholder_to_original, replaced_counts, unresolved)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            k: _walk(v, placeholder_to_original, replaced_counts, unresolved)
            for k, v in value.items()
        }
    return value


def rehydrate(
    summary: dict[str, Any], replacement_map: dict[str, str]
) -> RehydrationResult:
    """Replace placeholders in ``summary`` using ``replacement_map``.

    Placeholders not found in the map are left intact and recorded in
    ``unresolved_placeholders`` so the UI can flag them for clinician review.
    """
    placeholder_to_original = _invert_replacement_map(replacement_map)
    replaced_counts: dict[str, int] = {}
    unresolved: list[str] = []

    rehydrated = _walk(summary, placeholder_to_original, replaced_counts, unresolved)

    return RehydrationResult(
        rehydrated_summary=rehydrated,
        placeholders_replaced=replaced_counts,
        unresolved_placeholders=unresolved,
    )
