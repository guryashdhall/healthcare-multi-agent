"""Offline 'simulated LLM' summarizer.

The real Azure OpenAI summarizer is the source of truth. This module exists
as a deterministic fallback when the LLM is unavailable, and so the
**Safety Gate** toggle still produces a visible PHI leak with no network.

Behaviour:
- When called on **de-identified** input, it produces a structured summary
  that uses the placeholder tokens in roughly the same shape Azure OpenAI
  would produce (so the re-hydration tab still demonstrates the substitution).
- When called on **raw** input (safety gate OFF), it deliberately copies
  patient name, MRN, phone, and provider out of the note into the summary
  fields - mimicking what an unaligned LLM that obeyed a prompt-injection
  would do. This is a *fake* echo, clearly labelled in the UI as
  ``source: simulated_offline``.

This is for offline demonstration only. It is not a real model call.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Optional

from .safe_summarizer import (
    _CHIEF_CONCERN_KEYWORDS,
    _HISTORY_KEYWORDS,
    _MEDICATION_KEYWORDS,
    _RISK_RULES,
    _FOLLOWUP_RULES,
    _find_keywords,
    _find_medications,
)


_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")
_LABELLED_PHI_RE = re.compile(
    r"^\s*(Patient|Provider|MRN|Phone|DOB|Email|Address|Health Card|"
    r"Primary Provider|Consulting Provider|Cardiology Consult|Follow-up|"
    r"Visit Date|Next Cardiology)\s*[:\-]\s*(.+?)\s*$",
    re.MULTILINE,
)


def _patient_token(text: str) -> str:
    placeholders = _PLACEHOLDER_RE.findall(text)
    for p in placeholders:
        if "PATIENT_NAME" in p:
            return p
    return "the patient"


def _provider_token(text: str) -> str:
    placeholders = _PLACEHOLDER_RE.findall(text)
    for p in placeholders:
        if "PROVIDER_NAME" in p:
            return p
    return "the care team"


def _date_token(text: str) -> str:
    placeholders = _PLACEHOLDER_RE.findall(text)
    # Prefer a generic [DATE_N] (e.g. follow-up date) over [DOB_N].
    for p in placeholders:
        if p.startswith("[DATE_"):
            return p
    for p in placeholders:
        if "DOB" in p:
            return p
    return "the agreed date"


def _summarize_deidentified(text: str) -> dict[str, Any]:
    """Behave like a well-aligned LLM on de-identified input - reference
    placeholder tokens in the output so re-hydration has work to do."""
    chief_keywords = _find_keywords(text, _CHIEF_CONCERN_KEYWORDS)
    history = _find_keywords(text, _HISTORY_KEYWORDS)
    meds = _find_medications(text)
    risks = _find_keywords(text, _RISK_RULES)
    questions = _find_keywords(text, _FOLLOWUP_RULES)

    pname = _patient_token(text)
    prov = _provider_token(text)
    date = _date_token(text)

    if chief_keywords:
        chief_concern = (
            f"Patient {pname} presents with "
            + chief_keywords[0].lower()
            + (" and " + chief_keywords[1].lower() if len(chief_keywords) > 1 else "")
            + "."
        )
    else:
        chief_concern = f"Patient {pname} presents for routine review."

    follow_up = [f"Confirm follow-up with {prov} on or around {date}."]
    follow_up.extend(questions)

    return {
        "summary_type": "clinical_workflow_support",
        "disclaimer": "For clinician review only. Not a diagnosis.",
        "chief_concern": chief_concern,
        "relevant_history": history,
        "medications_mentioned": meds,
        "risk_flags": risks,
        "follow_up_questions": follow_up,
        "source_text_status": "deidentified",
    }


def _extract_labelled(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _LABELLED_PHI_RE.finditer(text):
        label = match.group(1)
        value = match.group(2).strip()
        if value:
            found.setdefault(label, value)
    return found


def _summarize_raw_unsafe(text: str) -> dict[str, Any]:
    """Behave like an LLM that has been prompt-injected - copy raw PHI from
    the note into the structured summary so the audience can SEE the leak."""
    base = _summarize_deidentified(text)  # gets clinical content right

    labelled = _extract_labelled(text)
    patient = labelled.get("Patient") or "Unknown patient"
    provider = (
        labelled.get("Primary Provider")
        or labelled.get("Provider")
        or labelled.get("Cardiology Consult")
        or "the attending"
    )
    mrn = labelled.get("MRN")
    phone = labelled.get("Phone")
    address = labelled.get("Address")
    date = labelled.get("Follow-up") or labelled.get("Visit Date")

    chief_keywords = _find_keywords(text, _CHIEF_CONCERN_KEYWORDS)
    if chief_keywords:
        cc = chief_keywords[0].lower()
        base["chief_concern"] = (
            f"Patient {patient} reports {cc}"
            + (f" - confirm MRN {mrn}." if mrn else ".")
        )
    else:
        base["chief_concern"] = (
            f"Patient {patient} presents for review"
            + (f" - confirm MRN {mrn}." if mrn else ".")
        )

    follow_up = []
    if provider and date:
        follow_up.append(
            f"Confirm follow-up with {provider} on {date}."
        )
    if phone:
        follow_up.append(f"Reach patient by phone at {phone} if rescheduling.")
    if address:
        follow_up.append(f"Mail clinic correspondence to {address}.")
    follow_up.extend(_find_keywords(text, _FOLLOWUP_RULES))
    base["follow_up_questions"] = follow_up
    base["source_text_status"] = "deidentified"  # the model THINKS it was clean

    return base


async def stream_simulated(
    text: str,
    *,
    safety_enabled: bool,
    on_token: Optional[Callable[[str], Awaitable[None]]] = None,
) -> dict[str, Any]:
    """Produce a simulated 'streamed' summary for offline demos.

    Tokens are emitted character-by-character (with small pauses) to mimic
    the visual feel of a live LLM stream.
    """
    import asyncio

    summary = (
        _summarize_deidentified(text)
        if safety_enabled
        else _summarize_raw_unsafe(text)
    )
    raw = json.dumps(summary, indent=2)

    if on_token is not None:
        # Stream in small chunks so the UI animates.
        chunk_size = 6
        for i in range(0, len(raw), chunk_size):
            await on_token(raw[i : i + chunk_size])
            await asyncio.sleep(0.01)
    return summary
