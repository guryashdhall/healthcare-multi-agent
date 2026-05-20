"""Safe deterministic summarizer.

This module is intentionally local and rule-based. The point of the demo is
the privacy/safety gate that runs *before* a model call - not the model itself.

A real deployment would call an LLM here, but only after:
- the input has been de-identified,
- PHI leakage validation has passed,
- prompt injection validation has passed,
- the call is wrapped in audit logging and human review controls.
"""

from __future__ import annotations

import re
from typing import Any


_CHIEF_CONCERN_KEYWORDS: list[tuple[str, str]] = [
    ("shortness of breath", "Shortness of breath"),
    ("chest tightness", "Chest tightness"),
    ("chest pain", "Chest pain"),
    ("dizziness", "Dizziness"),
    ("headache", "Headache"),
    ("fever", "Fever"),
    ("cough", "Cough"),
    ("wheeze", "Wheezing"),
    ("swelling", "Peripheral swelling"),
    ("pain", "Pain"),
]

_HISTORY_KEYWORDS: list[tuple[str, str]] = [
    ("copd", "COPD"),
    ("asthma", "Asthma"),
    ("type 2 diabetes", "Type 2 diabetes"),
    ("diabetes", "Diabetes"),
    ("hypertension", "Hypertension"),
    ("chronic kidney disease", "Chronic kidney disease"),
    ("ckd", "Chronic kidney disease"),
    ("chf", "Congestive heart failure"),
    ("heart failure", "Heart failure"),
    ("myocardial infarction", "Prior myocardial infarction"),
    ("ischemic heart disease", "Ischemic heart disease"),
]

_MEDICATION_KEYWORDS: list[str] = [
    "Salbutamol",
    "Prednisone",
    "Metformin",
    "Insulin",
    "Warfarin",
    "Lisinopril",
    "Atorvastatin",
    "Furosemide",
]

_RISK_RULES: list[tuple[str, str]] = [
    ("chest pain", "Chest pain - rule out acute coronary syndrome"),
    ("chest tightness", "Chest tightness - cardiopulmonary assessment"),
    ("shortness of breath", "Dyspnea - assess oxygenation and respiratory effort"),
    ("focal neurological", "Possible neurological symptoms - urgent assessment"),
    ("syncope", "Syncope - cardiac and neurological workup"),
    ("fever", "Fever - consider infection workup"),
    ("worsening", "Symptom escalation reported"),
    ("rescue inhaler", "Increased rescue inhaler use - asthma/COPD exacerbation"),
]

_FOLLOWUP_RULES: list[tuple[str, str]] = [
    ("shortness of breath", "Has dyspnea changed at rest vs on exertion?"),
    ("chest", "Any radiation, diaphoresis, or association with exertion?"),
    ("dizziness", "Postural component? Any associated visual or neurological symptoms?"),
    ("diabetes", "Recent HbA1c and glucose monitoring trends?"),
    ("hypertension", "Home BP readings and medication adherence?"),
    ("swelling", "Bilateral vs unilateral, weight change, orthopnea?"),
]


def _find_keywords(text: str, pairs: list[tuple[str, str]]) -> list[str]:
    lowered = text.lower()
    seen: list[str] = []
    for needle, label in pairs:
        if needle in lowered and label not in seen:
            seen.append(label)
    return seen


def _find_medications(text: str) -> list[str]:
    found: list[str] = []
    for med in _MEDICATION_KEYWORDS:
        if re.search(rf"\b{re.escape(med)}\b", text, flags=re.IGNORECASE):
            if med not in found:
                found.append(med)
    return found


def summarize_safely(deidentified_text: str) -> dict[str, Any]:
    """Produce a structured clinical-workflow-support summary.

    The function takes ONLY de-identified text. The caller is responsible for
    verifying that PHI leakage and prompt injection checks have passed first.
    """
    chief = _find_keywords(deidentified_text, _CHIEF_CONCERN_KEYWORDS)
    history = _find_keywords(deidentified_text, _HISTORY_KEYWORDS)
    medications = _find_medications(deidentified_text)
    risks = _find_keywords(deidentified_text, _RISK_RULES)
    followups = _find_keywords(deidentified_text, _FOLLOWUP_RULES)

    chief_concern = chief[0] if chief else "Not clearly stated in note"

    return {
        "summary_type": "clinical_workflow_support",
        "disclaimer": "For clinician review only. Not a diagnosis.",
        "chief_concern": chief_concern,
        "relevant_history": history,
        "medications_mentioned": medications,
        "risk_flags": risks,
        "follow_up_questions": followups,
        "source_text_status": "deidentified",
    }
