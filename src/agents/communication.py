"""Communication specialist agent: clinician handoff + patient-facing draft."""

from __future__ import annotations

from typing import Any, Optional

from .base import AgentResult, TokenCallback, call_azure_streaming, simulated_stream


NAME = "communication"
DISPLAY = "Communication"
ICON = "COM"

SYSTEM_PROMPT = (
    "You are a clinical communication specialist. Input is a de-identified "
    "case. Produce TWO drafts:\n"
    "  1. A concise structured clinician handoff (3-6 lines).\n"
    "  2. A plain-language patient-facing summary (under 120 words).\n"
    "Use placeholder tokens (like [PATIENT_NAME_1] or [PROVIDER_NAME_1]) "
    "whenever you would otherwise name the patient or provider. Preserve "
    "all placeholders verbatim. Respond with a single JSON object only:\n"
    "{"
    '"clinician_handoff_md": string, '
    '"patient_summary_md": string'
    "}"
)


async def run_communication_azure(
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
            "clinician_handoff_md": (
                "68F new AFib RVR, HR 132, BP 158/92, near-syncope. "
                "PMH HTN, CKD3 (eGFR 38), prior TIA, on warfarin (INR 2.4). "
                "Plan: amiodarone proposed - **flag interaction with warfarin "
                "via CYP2C9/3A4**; prefer rate control with metoprolol/"
                "diltiazem. CHADS2-VASc 4, continue anticoagulation. "
                "Echo within 2 weeks. Follow-up with [PROVIDER_NAME_1]."
            ),
            "patient_summary_md": (
                "Your heart is beating irregularly today, a condition called "
                "atrial fibrillation. We have several safe ways to control "
                "it. Before adding a new medicine, we want to make sure it "
                "won't interact with your blood thinner. Your team will "
                "decide between two approaches and you will be involved in "
                "the choice. Please continue your current medications and "
                "come back if you feel faint, very short of breath, or have "
                "chest pain."
            ),
        }
    if case_id == "case_singh_chest_pain":
        return {
            "clinician_handoff_md": (
                "54M sudden pleuritic chest pain, dyspnea, SpO2 93%, HR 108. "
                "Recent 10h flight. D-dimer 1850, troponin negative, CXR normal, "
                "no ST changes. **Working diagnosis pulmonary embolism, NOT "
                "ACS first.** CTPA pending; empirical anticoagulation if "
                "stable. Aspirin given - reassess once PE ruled in/out."
            ),
            "patient_summary_md": (
                "Your chest pain and low oxygen, plus your recent long "
                "flight, suggest a possible blood clot in the lung. We are "
                "doing a special CT scan to check. If confirmed, we will "
                "start a blood thinner immediately. Please tell us right "
                "away if your breathing gets worse, if you feel faint, or "
                "if you cough up blood."
            ),
        }
    if case_id == "case_chen_headache":
        return {
            "clinician_handoff_md": (
                "32F thunderclap-onset worst-of-life headache, photophobia, "
                "nuchal rigidity, low-grade fever, on OCP. **Treat as SAH/"
                "meningitis/CVST until imaging excludes.** Non-contrast CT "
                "head urgent; LP if CT negative and onset >6h. HOLD "
                "ketorolac until imaging cleared. Do NOT discharge with "
                "'migraine' label."
            ),
            "patient_summary_md": (
                "Your sudden, severe headache with stiff neck needs urgent "
                "brain imaging today before we treat the pain. There are a "
                "few serious causes we want to rule out first. We will not "
                "give you a pain shot that could cause harm if there is "
                "bleeding. Please stay in the department until imaging is "
                "complete - this is for your safety."
            ),
        }
    if case_id == "case_patel_falls":
        return {
            "clinician_handoff_md": (
                "76M three falls, subacute cognitive decline (MMSE 28 -> 22), "
                "dry mouth, orthostatic drop 26 mmHg. **High anticholinergic "
                "burden (ACB ~11) across oxybutynin, diphenhydramine, "
                "amitriptyline, lorazepam, loratadine.** Plan: deprescribe "
                "first (stop diphenhydramine, taper amitriptyline + "
                "lorazepam, swap oxybutynin to mirabegron). Reassess "
                "cognition in 6-8 weeks. CT head to rule out SDH. "
                "Defer rivastigmine."
            ),
            "patient_summary_md": (
                "Many of the symptoms you and your daughter described - the "
                "confusion, dry mouth, falls, and sleepiness - can be caused "
                "by medications working together. We want to safely stop or "
                "swap a few of them, then see how you feel in 6-8 weeks "
                "before deciding anything about dementia. Please do not "
                "stop any medication on your own; your pharmacist will give "
                "you a clear taper plan."
            ),
        }
    return {
        "clinician_handoff_md": "Insufficient structured input for handoff draft.",
        "patient_summary_md": "Insufficient structured input for patient summary.",
    }


async def run_communication_simulated(
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
