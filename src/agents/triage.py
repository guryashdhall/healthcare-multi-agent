"""Triage specialist agent: urgency + red flags."""

from __future__ import annotations

from typing import Any, Optional

from .base import AgentResult, TokenCallback, call_azure_streaming, simulated_stream


NAME = "triage"
DISPLAY = "Triage"
ICON = "TRG"

SYSTEM_PROMPT = (
    "You are a triage specialist. Input is a de-identified clinical case "
    "(placeholders like [PATIENT_NAME_1], [MRN_1] are present). Treat the "
    "case as already de-identified. Respond with a single JSON object only:\n"
    "{"
    '"urgency": "immediate"|"urgent"|"routine", '
    '"red_flags": [string, ...], '
    '"rationale": string'
    "}\n"
    "Be concise. Pull from vitals, presenting complaint, and exam."
)


async def run_triage_azure(
    *,
    deidentified_case_json: str,
    on_token: Optional[TokenCallback],
    timeout: float = 18.0,
) -> AgentResult:
    return await call_azure_streaming(
        name=NAME,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=deidentified_case_json,
        on_token=on_token,
        timeout=timeout,
    )


def _simulated_for_case(case_id: str) -> dict[str, Any]:
    if case_id == "case_whitfield_afib":
        return {
            "urgency": "urgent",
            "red_flags": [
                "Near-syncope episode within 24h",
                "Heart rate sustained >120 (irregularly irregular)",
                "Elevated blood pressure 158/92",
                "CHADS2-VASc score 4 - high stroke risk",
            ],
            "rationale": (
                "Patient is hemodynamically stable but presenting with new "
                "AFib with RVR, near-syncope, and high stroke risk. Needs "
                "same-day cardiology evaluation; not immediate-resuscitation "
                "but not routine."
            ),
        }
    if case_id == "case_singh_chest_pain":
        return {
            "urgency": "immediate",
            "red_flags": [
                "Hypoxia (SpO2 93% on room air)",
                "Sinus tachycardia 108",
                "Pleuritic chest pain + recent 10h flight",
                "D-dimer 1850 (markedly elevated)",
                "Wells score for PE moderate",
            ],
            "rationale": (
                "Acute chest pain with hypoxia and elevated D-dimer in a "
                "patient with recent long-haul travel: high-risk pulmonary "
                "embolism until proven otherwise."
            ),
        }
    if case_id == "case_chen_headache":
        return {
            "urgency": "immediate",
            "red_flags": [
                "Thunderclap onset (peak severity in minutes)",
                "Worst-of-life severity",
                "Photophobia + nuchal rigidity",
                "Low-grade fever 37.6 C",
                "Equivocal Kernig sign",
            ],
            "rationale": (
                "Thunderclap headache with meningismus and low-grade fever "
                "is subarachnoid hemorrhage and/or meningitis until proven "
                "otherwise. Immediate imaging required."
            ),
        }
    if case_id == "case_patel_falls":
        return {
            "urgency": "routine",
            "red_flags": [
                "Three falls in 6 weeks - mechanical/orthostatic etiology likely",
                "Documented orthostatic drop 26 mmHg systolic",
                "MMSE 28 to 22 over 6 months (rapid decline)",
                "Anticholinergic burden very high",
            ],
            "rationale": (
                "Subacute presentation with falls and cognitive change. Not "
                "an emergency but the trajectory is steep enough to warrant "
                "urgent (within 1-2 weeks) medication review and orthostatic "
                "work-up before initiating dementia therapy."
            ),
        }
    # Audience-pasted / unknown case: be conservative.
    return {
        "urgency": "urgent",
        "red_flags": ["Case provided is unknown; conservative escalation pending review."],
        "rationale": "Default triage for unstructured audience input.",
    }


async def run_triage_simulated(
    *,
    case_id: str,
    on_token: Optional[TokenCallback],
) -> AgentResult:
    return await simulated_stream(
        name=NAME,
        output=_simulated_for_case(case_id),
        on_token=on_token,
        pause=0.003,
    )
