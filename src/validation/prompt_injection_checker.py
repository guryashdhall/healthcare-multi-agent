"""Prompt injection detector for clinical text.

Looks for instruction-like phrases that try to override system behavior or
exfiltrate PHI. This is a deterministic, list-based check for the demo. A
production system would layer this with model-based classifiers, content
provenance tracking, and structured input separation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class InjectionFinding:
    pattern: str
    matched_text: str
    start_index: int
    end_index: int

    def as_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "matched_text": self.matched_text,
            "start_index": self.start_index,
            "end_index": self.end_index,
        }


@dataclass
class InjectionResult:
    passed: bool
    findings: list[InjectionFinding] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "findings": [f.as_dict() for f in self.findings],
        }


# Each entry is a short label and a regex. Patterns are intentionally generous;
# in a real deployment you would tune precision/recall against a labelled set.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_previous_instructions", re.compile(r"(?i)ignore (?:all )?previous instructions")),
    ("override_system_instructions", re.compile(r"(?i)override (?:the )?system instructions?")),
    ("disregard_privacy_rules", re.compile(r"(?i)disregard (?:the )?privacy(?: rules)?")),
    ("reveal_patient_details", re.compile(r"(?i)reveal (?:the )?patient details?")),
    ("include_patient_name", re.compile(r"(?i)include the patient(?:['’]s)? (?:full )?name")),
    ("include_full_address", re.compile(r"(?i)include (?:the )?full address")),
    ("output_the_mrn", re.compile(r"(?i)output the mrn")),
    ("send_raw_note", re.compile(r"(?i)send (?:the )?raw note")),
    ("expose_confidential_data", re.compile(r"(?i)expose (?:the )?confidential data")),
    ("system_note_directive", re.compile(r"(?i)system note[:\s]")),
    ("act_as_role_override", re.compile(r"(?i)act as (?:a )?(?:system|admin|developer)")),
    ("disable_safety", re.compile(r"(?i)disable (?:the )?safety|disable (?:the )?guardrails?")),
]


def check_prompt_injection(text: str) -> InjectionResult:
    """Detect prompt-injection-like instructions inside ``text``."""
    findings: list[InjectionFinding] = []
    for label, pattern in _INJECTION_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                InjectionFinding(
                    pattern=label,
                    matched_text=match.group(0),
                    start_index=match.start(),
                    end_index=match.end(),
                )
            )
    return InjectionResult(passed=not findings, findings=findings)
