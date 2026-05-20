"""Pattern-based PHI/PII detector.

DEMO ONLY: This is a deterministic, regex/heuristic-based detector built for
a live demonstration of privacy-preserving engineering patterns. It is NOT a
production-grade de-identification engine. Real deployments must use a
healthcare-specific NLP de-identification stack (e.g., Presidio with custom
recognizers, Philter, MITRE Scrubber, or a clinical NER model) plus expert
review and a privacy impact assessment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PHIEntity:
    """A single detected PHI/PII span."""

    entity_type: str
    matched_text: str
    start_index: int
    end_index: int

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "matched_text": self.matched_text,
            "start_index": self.start_index,
            "end_index": self.end_index,
        }


# Order matters: more specific patterns first so they win over generic ones.
# Each tuple is (entity_type, compiled_regex). Patterns use named groups where
# the actual PHI span is in group "value"; otherwise the whole match is used.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "EMAIL",
        re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    ),
    (
        "PHONE",
        re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    ),
    (
        "HEALTH_CARD",
        re.compile(r"\b[A-Z]{2}-\d{4}-\d{3}-\d{3}\b"),
    ),
    (
        "MRN",
        re.compile(r"\b(?:MRN[:\s]+)?(?P<value>[A-Z]{2,4}-\d{5,7})\b"),
    ),
    (
        "POSTAL_CODE",
        # Canadian postal code, e.g. B3J 2H7
        re.compile(r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b"),
    ),
    (
        "DOB",
        # Labelled DOB with ISO date
        re.compile(r"(?i)\bDOB[:\s]+(?P<value>\d{4}-\d{2}-\d{2})\b"),
    ),
    (
        "DATE",
        # ISO dates not already captured as DOB
        re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    ),
    (
        "DATE",
        # Long-form dates like "May 4, 2026"
        re.compile(
            r"\b(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{1,2},\s+\d{4}\b"
        ),
    ),
    (
        "PROVIDER_NAME",
        # "Dr. First Last" - capture the title plus name. Use literal spaces
        # (not \s+) so the match cannot run across newlines.
        re.compile(r"\bDr\. [A-Z][a-z]+(?: [A-Z][a-z]+){1,2}\b"),
    ),
    (
        "PATIENT_NAME",
        # "Patient: First Last" - capture the name only. Anchor to a line and
        # use literal spaces inside the name.
        re.compile(
            r"(?m)^[ \t]*Patient[:\s]+(?P<value>[A-Z][a-z]+(?: [A-Z][a-z]+){1,3})[ \t]*$"
        ),
    ),
    (
        "ADDRESS",
        # Numbered street address, e.g. "145 Queen Street, Halifax, NS".
        # Literal spaces only - addresses fit on one line.
        re.compile(
            r"\b\d{1,5} [A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)* "
            r"(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|"
            r"Way|Court|Ct|Place|Pl)"
            r"(?:, [A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*)?"
            r"(?:, [A-Z]{2})?"
        ),
    ),
]


def _iter_matches(text: str) -> Iterable[PHIEntity]:
    """Yield candidate PHI entities from the text in pattern order."""
    for entity_type, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if "value" in match.groupdict() and match.group("value") is not None:
                start = match.start("value")
                end = match.end("value")
                value = match.group("value")
            else:
                start = match.start()
                end = match.end()
                value = match.group(0)
            yield PHIEntity(
                entity_type=entity_type,
                matched_text=value,
                start_index=start,
                end_index=end,
            )


def _resolve_overlaps(entities: list[PHIEntity]) -> list[PHIEntity]:
    """Remove entity spans that overlap an earlier (higher-priority) entity."""
    sorted_entities = sorted(entities, key=lambda e: (e.start_index, -e.end_index))
    accepted: list[PHIEntity] = []
    occupied: list[tuple[int, int]] = []

    for entity in sorted_entities:
        overlap = any(
            entity.start_index < end and entity.end_index > start
            for start, end in occupied
        )
        if overlap:
            continue
        accepted.append(entity)
        occupied.append((entity.start_index, entity.end_index))
    return accepted


def detect_phi(text: str) -> list[PHIEntity]:
    """Detect PHI/PII entities in ``text``.

    Returns a list of :class:`PHIEntity` ordered by position. The detector is
    deterministic and pattern-based; see module docstring for limitations.
    """
    candidates = list(_iter_matches(text))
    # Pattern order in _PATTERNS gives priority. We re-rank candidates so that
    # earlier-listed patterns win on overlap.
    pattern_priority = {entity_type: idx for idx, (entity_type, _) in enumerate(_PATTERNS)}
    candidates.sort(
        key=lambda e: (
            pattern_priority.get(e.entity_type, 99),
            e.start_index,
        )
    )
    return sorted(_resolve_overlaps(candidates), key=lambda e: e.start_index)


def count_by_type(entities: list[PHIEntity]) -> dict[str, int]:
    """Return a {entity_type: count} dict suitable for audit logs."""
    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    return counts
