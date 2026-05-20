"""Post-redaction PHI leakage validator.

Runs after de-identification to confirm no obvious PHI-shaped strings remain.
This is a fail-closed safety gate: if anything risky is found, the pipeline
must block summarization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class LeakageFinding:
    category: str
    matched_text: str
    start_index: int
    end_index: int

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            # We deliberately store only a short, masked representation so the
            # finding itself can never become a source of PHI leakage.
            "preview": _mask(self.matched_text),
            "start_index": self.start_index,
            "end_index": self.end_index,
        }


@dataclass
class LeakageResult:
    passed: bool
    leakage_findings: list[LeakageFinding] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "leakage_findings": [f.as_dict() for f in self.leakage_findings],
        }


def _mask(value: str) -> str:
    """Return a short, redacted preview safe to store in audit logs."""
    if len(value) <= 4:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]


_LEAKAGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PHONE", re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b")),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("MRN", re.compile(r"\b[A-Z]{2,4}-\d{5,7}\b")),
    ("HEALTH_CARD", re.compile(r"\b[A-Z]{2}-\d{4}-\d{3}-\d{3}\b")),
    ("DOB_LABEL", re.compile(r"(?i)\bDOB[:\s]+\d{4}-\d{2}-\d{2}\b")),
    ("ISO_DATE", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    (
        "STREET_ADDRESS",
        re.compile(
            r"\b\d{1,5}\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+"
            r"(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln)\b"
        ),
    ),
    (
        "PATIENT_NAME_AFTER_LABEL",
        # Multiline only - case must stay strict so "Patient presents with..."
        # (lowercase verb) does not falsely match.
        re.compile(r"(?m)^[ \t]*Patient[:\s]+(?!\[)[A-Z][a-z]+(?: [A-Z][a-z]+)+"),
    ),
    (
        "PROVIDER_NAME_AFTER_DR",
        re.compile(r"\bDr\. (?!\[)[A-Z][a-z]+(?: [A-Z][a-z]+)+"),
    ),
    ("POSTAL_CODE", re.compile(r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b")),
]


def check_phi_leakage(text: str) -> LeakageResult:
    """Scan ``text`` for PHI-shaped patterns that survived de-identification."""
    findings: list[LeakageFinding] = []
    for category, pattern in _LEAKAGE_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                LeakageFinding(
                    category=category,
                    matched_text=match.group(0),
                    start_index=match.start(),
                    end_index=match.end(),
                )
            )
    return LeakageResult(passed=not findings, leakage_findings=findings)
