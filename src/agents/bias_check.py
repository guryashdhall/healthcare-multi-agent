"""Bias-check specialist agent: flags cognitive biases in the proposed plan."""

from __future__ import annotations

from typing import Any, Optional

from .base import AgentResult, TokenCallback, call_azure_streaming, simulated_stream


NAME = "bias_check"
DISPLAY = "Bias Check"
ICON = "BIA"

SYSTEM_PROMPT = (
    "You are a clinical reasoning auditor. Input is a de-identified case "
    "including the clinician's initial plan. Look for cognitive biases - "
    "anchoring, premature closure, availability, confirmation, and "
    "iatrogenesis blindness. Respond with a single JSON object only:\n"
    "{"
    '"biases": ['
    '  {"type": string, "evidence_in_note": string, "mitigation": string}'
    "], "
    '"unconsidered_alternatives": [string]'
    "}\n"
    "If you find no significant biases, return an empty list rather than "
    "inventing concerns."
)


async def run_bias_check_azure(
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
            "biases": [
                {
                    "type": "Anchoring on rhythm control",
                    "evidence_in_note": (
                        "Plan jumps to amiodarone as first-line in a stable "
                        "patient. Rate control (beta blocker or non-DHP CCB) "
                        "is a reasonable first-line per current guideline."
                    ),
                    "mitigation": (
                        "Explicitly consider rate vs rhythm control; if rate, "
                        "metoprolol or diltiazem; if rhythm, address warfarin "
                        "interaction proactively."
                    ),
                },
                {
                    "type": "Iatrogenesis blindness",
                    "evidence_in_note": (
                        "The plan adds amiodarone without mentioning the "
                        "warfarin-amiodarone interaction. Same root issue "
                        "Pharmacy flagged."
                    ),
                    "mitigation": "Cross-check every new medication against the existing list.",
                },
            ],
            "unconsidered_alternatives": [
                "Rate control with metoprolol or diltiazem alone",
                "DOAC substitution for warfarin if rhythm control is essential",
            ],
        }
    if case_id == "case_singh_chest_pain":
        return {
            "biases": [
                {
                    "type": "Premature closure on ACS",
                    "evidence_in_note": (
                        "Plan commits to chest pain observation despite "
                        "pleuritic character, hypoxia, recent long flight, "
                        "and markedly elevated D-dimer all pointing at PE."
                    ),
                    "mitigation": (
                        "CT pulmonary angiogram before locking the ACS "
                        "pathway. Empirical anticoagulation while imaging "
                        "if probability remains moderate-high."
                    ),
                },
                {
                    "type": "Availability bias",
                    "evidence_in_note": (
                        "Cardiac risk factors are familiar; the team may be "
                        "reaching for the most-rehearsed differential."
                    ),
                    "mitigation": "Reason from base rates and pretest probability tools.",
                },
            ],
            "unconsidered_alternatives": [
                "Pulmonary embolism (high priority)",
                "Pneumothorax",
                "Pericarditis",
            ],
        }
    if case_id == "case_chen_headache":
        return {
            "biases": [
                {
                    "type": "Premature closure on migraine",
                    "evidence_in_note": (
                        "Plan labels as migraine without imaging despite "
                        "thunderclap onset, worst-of-life severity, fever, "
                        "and nuchal rigidity."
                    ),
                    "mitigation": (
                        "Thunderclap headache is SAH/meningitis until proven "
                        "otherwise. Imaging precedes any therapeutic label."
                    ),
                },
                {
                    "type": "Confirmation bias",
                    "evidence_in_note": (
                        "Family history of migraine is being used to confirm "
                        "the diagnosis; it does not reduce risk of secondary "
                        "headache."
                    ),
                    "mitigation": "Treat thunderclap criteria as a hard imaging trigger.",
                },
            ],
            "unconsidered_alternatives": [
                "Subarachnoid hemorrhage",
                "Bacterial meningitis",
                "Cerebral venous sinus thrombosis (OCP user)",
            ],
        }
    if case_id == "case_patel_falls":
        return {
            "biases": [
                {
                    "type": "Iatrogenesis blindness (primary)",
                    "evidence_in_note": (
                        "Plan reaches for a dementia diagnosis and adds "
                        "rivastigmine despite a medication list that fully "
                        "explains the symptoms."
                    ),
                    "mitigation": (
                        "When a new symptom presents, review the medication "
                        "list within 30 days of onset. Deprescribe first."
                    ),
                },
                {
                    "type": "Availability bias",
                    "evidence_in_note": (
                        "Cognitive decline pattern in older adults primes "
                        "the team toward 'dementia' as the most-rehearsed "
                        "diagnosis."
                    ),
                    "mitigation": "Anticholinergic Cognitive Burden score before label.",
                },
            ],
            "unconsidered_alternatives": [
                "Reversible iatrogenic cognitive impairment",
                "Orthostatic hypotension causing falls (already documented)",
                "Subdural hematoma from unwitnessed falls (rule out with CT)",
            ],
        }
    return {
        "biases": [],
        "unconsidered_alternatives": [],
    }


async def run_bias_check_simulated(
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
