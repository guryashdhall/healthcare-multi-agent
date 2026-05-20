"""Pharmacy specialist agent: interactions, dose-for-renal, polypharmacy.

This is the agent that catches the hero-case warfarin/amiodarone interaction.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import AgentResult, TokenCallback, call_azure_streaming, simulated_stream


NAME = "pharmacy"
DISPLAY = "Pharmacy"
ICON = "Rx"

SYSTEM_PROMPT = (
    "You are a clinical pharmacist specialist. Input is a de-identified "
    "clinical case (placeholders for PHI are present). Focus on: "
    "(1) drug-drug interactions including any NEW medications proposed in "
    "the clinician's initial plan, (2) dose appropriateness given renal "
    "and hepatic function, (3) total polypharmacy / anticholinergic burden "
    "in older adults. Respond with a single JSON object only:\n"
    "{"
    '"interactions": ['
    '  {"drugs": [string], "mechanism": string, "severity": "high"|"med"|"low", "recommendation": string}'
    "], "
    '"dose_concerns": [string], '
    '"polypharmacy_score": integer 0-10, '
    '"anticholinergic_burden_score": integer 0-15, '
    '"top_recommendation": string'
    "}\n"
    "Be specific. Reference the offending drugs by name."
)


async def run_pharmacy_azure(
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
            "interactions": [
                {
                    "drugs": ["Amiodarone (proposed)", "Warfarin (existing)"],
                    "mechanism": (
                        "Amiodarone inhibits CYP2C9 (S-warfarin metabolism) "
                        "and CYP3A4 (R-warfarin), increasing warfarin AUC."
                    ),
                    "severity": "high",
                    "recommendation": (
                        "Reduce warfarin dose by 30-50% pre-emptively on day "
                        "of amiodarone start; recheck INR every 3-4 days for "
                        "2 weeks. INR is projected to reach 4.5+ within 7-10 "
                        "days without dose adjustment. Consider rate-control "
                        "alternative (metoprolol or diltiazem) as first-line "
                        "instead per current AFib guideline."
                    ),
                },
                {
                    "drugs": ["Amiodarone (proposed)", "Lisinopril (existing)"],
                    "mechanism": "Minor; mild additive bradycardia and hypotension risk.",
                    "severity": "low",
                    "recommendation": "Monitor BP and HR after initiation.",
                },
            ],
            "dose_concerns": [
                "CKD stage 3 (eGFR 38): if DOAC is considered as warfarin alternative, "
                "apixaban dose-reduce per criteria; rivaroxaban OK at 15 mg/d.",
                "Atorvastatin: amiodarone can increase atorvastatin levels - watch for myopathy.",
            ],
            "polypharmacy_score": 4,
            "anticholinergic_burden_score": 0,
            "top_recommendation": (
                "Reconsider amiodarone in favor of metoprolol/diltiazem rate "
                "control. If rhythm control is essential, reduce warfarin "
                "dose 30-50% and INR-monitor q3-4 days."
            ),
        }
    if case_id == "case_singh_chest_pain":
        return {
            "interactions": [
                {
                    "drugs": ["Aspirin (proposed)", "Amlodipine (existing)"],
                    "mechanism": "No significant interaction.",
                    "severity": "low",
                    "recommendation": "OK if ACS rules in.",
                },
            ],
            "dose_concerns": [
                "If PE confirmed and anticoagulation initiated: full-dose LMWH or DOAC; "
                "no renal dose adjustment needed at Cr 0.9.",
                "Hold aspirin if PE confirmed and anticoagulation started, unless ACS "
                "diagnosis remains in play.",
            ],
            "polypharmacy_score": 1,
            "anticholinergic_burden_score": 0,
            "top_recommendation": (
                "Imaging-first (CTPA) BEFORE empirical ACS therapy commits "
                "the patient to a clopidogrel-aspirin pathway."
            ),
        }
    if case_id == "case_chen_headache":
        return {
            "interactions": [
                {
                    "drugs": ["Combined OCP", "Headache + photophobia + nuchal rigidity"],
                    "mechanism": (
                        "Estrogen-containing OCPs modestly raise risk of cerebral venous "
                        "sinus thrombosis and ischemic stroke; relevant context, not a direct "
                        "drug-drug interaction."
                    ),
                    "severity": "med",
                    "recommendation": (
                        "Stop OCP if SAH/CVST confirmed; non-hormonal contraception "
                        "going forward."
                    ),
                },
            ],
            "dose_concerns": [
                "Ketorolac in patients with potential intracranial bleeding is "
                "contraindicated - HOLD until imaging excludes hemorrhage."
            ],
            "polypharmacy_score": 1,
            "anticholinergic_burden_score": 0,
            "top_recommendation": (
                "Do NOT administer ketorolac before CT head. Treat as "
                "thunderclap headache work-up first; analgesia second."
            ),
        }
    if case_id == "case_patel_falls":
        return {
            "interactions": [
                {
                    "drugs": ["Oxybutynin", "Diphenhydramine", "Amitriptyline"],
                    "mechanism": (
                        "All three are strongly anticholinergic. Additive ACB "
                        "score >=9. Causally linked to cognitive impairment, "
                        "falls, orthostatic hypotension, dry mouth."
                    ),
                    "severity": "high",
                    "recommendation": (
                        "Deprescribe diphenhydramine first (OTC, no clinical "
                        "indication that justifies cost). Swap oxybutynin to "
                        "mirabegron. Taper amitriptyline 25 mg over 4-6 "
                        "weeks; consider SSRI alternative."
                    ),
                },
                {
                    "drugs": ["Lorazepam", "All sedating agents above"],
                    "mechanism": "Additive sedation and fall risk in older adult.",
                    "severity": "high",
                    "recommendation": "Taper and discontinue lorazepam per Beers Criteria.",
                },
                {
                    "drugs": ["Hydrochlorothiazide", "Postural drop"],
                    "mechanism": "Volume contraction contributing to orthostatic hypotension.",
                    "severity": "med",
                    "recommendation": "Reduce dose or switch to ACEi-only regimen.",
                },
            ],
            "dose_concerns": [
                "eGFR 52 - HCTZ less effective; consider switching antihypertensive.",
            ],
            "polypharmacy_score": 9,
            "anticholinergic_burden_score": 11,
            "top_recommendation": (
                "Do NOT add a cholinesterase inhibitor on top of strong "
                "anticholinergics - it is pharmacologically contradictory. "
                "Deprescribe first, reassess cognition in 6-8 weeks."
            ),
        }
    return {
        "interactions": [],
        "dose_concerns": [],
        "polypharmacy_score": 0,
        "anticholinergic_burden_score": 0,
        "top_recommendation": "Insufficient medication data for analysis.",
    }


async def run_pharmacy_simulated(
    *,
    case_id: str,
    on_token: Optional[TokenCallback],
) -> AgentResult:
    return await simulated_stream(
        name=NAME,
        output=_simulated_for_case(case_id),
        on_token=on_token,
        pause=0.004,
    )
