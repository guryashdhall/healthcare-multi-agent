"""Differential diagnosis specialist agent."""

from __future__ import annotations

from typing import Any, Optional

from .base import AgentResult, TokenCallback, call_azure_streaming, simulated_stream


NAME = "differential"
DISPLAY = "Differential Dx"
ICON = "DDX"

SYSTEM_PROMPT = (
    "You are a clinical reasoning specialist focused on differential "
    "diagnosis. Input is a de-identified clinical case. Produce a ranked "
    "differential with supporting and refuting evidence drawn from the "
    "case. Respond with a single JSON object only:\n"
    "{"
    '"ranked_dx": ['
    '  {"dx": string, "probability": "high"|"moderate"|"low", '
    '   "supporting": [string], "refuting": [string]}'
    "], "
    '"next_steps": [string]'
    "}\n"
    "Give 3-5 differentials. Prioritize what should change management."
)


async def run_differential_azure(
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
            "ranked_dx": [
                {
                    "dx": "New-onset atrial fibrillation with rapid ventricular response",
                    "probability": "high",
                    "supporting": [
                        "Irregularly irregular pulse at 132",
                        "ECG: AFib with RVR",
                        "Palpitations + near-syncope",
                    ],
                    "refuting": ["No prior history; no obvious precipitant"],
                },
                {
                    "dx": "Hyperthyroidism precipitating AFib",
                    "probability": "low",
                    "supporting": ["AFib in older woman"],
                    "refuting": ["TSH 1.8 (normal)"],
                },
                {
                    "dx": "Pulmonary embolism causing tachyarrhythmia",
                    "probability": "low",
                    "supporting": ["Mild dyspnea on exertion"],
                    "refuting": ["No hypoxia, no pleuritic pain, no immobility risk factors"],
                },
            ],
            "next_steps": [
                "Confirm AFib with 12-lead ECG (already done)",
                "Echocardiogram to assess LVEF, atrial size, valvular disease",
                "Thyroid panel (already TSH normal)",
                "Decision on rate vs rhythm control",
            ],
        }
    if case_id == "case_singh_chest_pain":
        return {
            "ranked_dx": [
                {
                    "dx": "Pulmonary embolism",
                    "probability": "high",
                    "supporting": [
                        "Pleuritic chest pain",
                        "Hypoxia (SpO2 93%)",
                        "Sinus tachycardia",
                        "Recent 10h flight",
                        "D-dimer 1850",
                        "Wells score moderate",
                    ],
                    "refuting": ["No overt leg swelling"],
                },
                {
                    "dx": "Acute coronary syndrome",
                    "probability": "low",
                    "supporting": ["Chest pain with cardiac risk factors"],
                    "refuting": [
                        "Pleuritic character",
                        "Normal initial troponin",
                        "No ST changes",
                    ],
                },
                {
                    "dx": "Spontaneous pneumothorax",
                    "probability": "low",
                    "supporting": ["Sudden onset pleuritic pain"],
                    "refuting": ["CXR reported normal"],
                },
            ],
            "next_steps": [
                "CT pulmonary angiogram NOW (before ACS pathway commits)",
                "If CTPA unavailable, V/Q scan",
                "Lower-extremity Doppler in parallel",
                "Empirical anticoagulation while imaging if hemodynamically stable and bleeding risk acceptable",
            ],
        }
    if case_id == "case_chen_headache":
        return {
            "ranked_dx": [
                {
                    "dx": "Subarachnoid hemorrhage",
                    "probability": "high",
                    "supporting": [
                        "Thunderclap onset",
                        "Worst-of-life severity",
                        "Nuchal rigidity",
                        "OCP user (modest CVST risk)",
                    ],
                    "refuting": ["No focal deficit (yet)"],
                },
                {
                    "dx": "Bacterial or viral meningitis",
                    "probability": "moderate",
                    "supporting": ["Low-grade fever, nuchal rigidity, photophobia, leukocytosis"],
                    "refuting": ["Onset is more abrupt than typical meningitis"],
                },
                {
                    "dx": "Migraine, first severe presentation",
                    "probability": "low",
                    "supporting": ["Photophobia, nausea/vomiting, family history"],
                    "refuting": ["Thunderclap onset is atypical for migraine"],
                },
                {
                    "dx": "Cerebral venous sinus thrombosis",
                    "probability": "moderate",
                    "supporting": ["OCP use, severe headache, female of reproductive age"],
                    "refuting": ["Onset somewhat abrupt for CVST"],
                },
            ],
            "next_steps": [
                "Non-contrast CT head IMMEDIATELY",
                "Lumbar puncture if CT negative and >6h since onset",
                "MRV if CVST suspected",
                "Do not discharge with 'migraine' label until imaging negative",
            ],
        }
    if case_id == "case_patel_falls":
        return {
            "ranked_dx": [
                {
                    "dx": "Iatrogenic cognitive impairment + falls from anticholinergic burden",
                    "probability": "high",
                    "supporting": [
                        "Five concurrent strong anticholinergics",
                        "Dry mouth, mid-dilated pupils",
                        "Orthostatic drop 26 mmHg",
                        "Subacute decline timeline matches medication accumulation",
                    ],
                    "refuting": [],
                },
                {
                    "dx": "Major neurocognitive disorder (Alzheimer or vascular type)",
                    "probability": "low",
                    "supporting": ["MMSE decline 28 to 22"],
                    "refuting": ["Decline is too rapid; reversible causes not yet excluded"],
                },
                {
                    "dx": "Subdural hematoma from unwitnessed falls",
                    "probability": "low",
                    "supporting": ["Older adult with falls, cognitive change"],
                    "refuting": ["No focal deficits; will rule out with imaging"],
                },
            ],
            "next_steps": [
                "Deprescribe / taper anticholinergics and sedatives first",
                "Reassess cognition 6-8 weeks after deprescribing",
                "Non-contrast CT head to rule out SDH",
                "Postural BPs already documented orthostatic",
            ],
        }
    return {
        "ranked_dx": [
            {
                "dx": "Insufficient structured data to differential",
                "probability": "low",
                "supporting": [],
                "refuting": [],
            }
        ],
        "next_steps": ["Structured intake before differential is reliable."],
    }


async def run_differential_simulated(
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
