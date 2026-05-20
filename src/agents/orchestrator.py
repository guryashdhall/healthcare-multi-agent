"""Orchestrator: fan-in synthesizer.

Receives all six specialist agents' outputs and produces a single ranked
action plan plus a list of cross-agent flags (where two or more agents
converged on the same concern, raising severity).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .base import AgentResult, TokenCallback, call_azure_streaming, simulated_stream


NAME = "orchestrator"
DISPLAY = "Orchestrator"
ICON = "ORC"

SYSTEM_PROMPT = (
    "You are the orchestrator for a clinical co-pilot. Your input is a "
    "JSON object containing six specialist agents' outputs (triage, "
    "differential, pharmacy, guidelines, bias_check, communication). "
    "Synthesize them into a single ranked action plan and identify "
    "cross-agent convergence (where two or more agents independently "
    "flagged the same concern - those are high-severity).\n"
    "Respond with a single JSON object only:\n"
    "{"
    '"summary": string, '
    '"ranked_actions": ['
    '  {"action": string, "rationale": string, "agents_supporting": [string], "priority": "high"|"med"|"low"}'
    "], "
    '"cross_flags": ['
    '  {"flag": string, "agents": [string], "severity": "high"|"med"|"low"}'
    "], "
    '"patient_facing": string'
    "}\n"
    "Use placeholder tokens (like [PATIENT_NAME_1]) verbatim - they will be "
    "re-substituted server-side before the clinician sees this."
)


def _cross_flag_heuristic(specialist_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Local convergence detector used by the simulated orchestrator.

    Searches all specialists' free-text fields for shared keywords - drug
    names, condition names, etc. - and flags converged concerns.
    """
    text_per_agent: dict[str, str] = {}
    for name, out in specialist_outputs.items():
        text_per_agent[name] = json.dumps(out).lower()

    candidates: list[tuple[str, str]] = [
        ("amiodarone", "Amiodarone-warfarin interaction"),
        ("pulmonary embolism", "Pulmonary embolism work-up takes priority over ACS"),
        ("subarachnoid", "Imaging required before migraine label"),
        ("thunderclap", "Imaging required before migraine label"),
        ("anticholinergic", "Anticholinergic burden is the leading explanation"),
        ("polypharmacy", "Anticholinergic burden is the leading explanation"),
    ]
    flags: list[dict[str, Any]] = []
    seen_flags: set[str] = set()
    for keyword, flag_text in candidates:
        agents_hit = [a for a, t in text_per_agent.items() if keyword in t]
        if len(agents_hit) >= 2 and flag_text not in seen_flags:
            flags.append(
                {
                    "flag": flag_text,
                    "agents": sorted(agents_hit),
                    "severity": "high",
                }
            )
            seen_flags.add(flag_text)
    return flags


async def run_orchestrator_azure(
    *,
    specialist_outputs: dict[str, Any],
    on_token: Optional[TokenCallback],
    timeout: float = 25.0,
) -> AgentResult:
    user_prompt = json.dumps(specialist_outputs, indent=2)
    return await call_azure_streaming(
        name=NAME,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        on_token=on_token,
        timeout=timeout,
    )


def _simulated_for_case(case_id: str, specialist_outputs: dict[str, Any]) -> dict[str, Any]:
    cross_flags = _cross_flag_heuristic(specialist_outputs)

    if case_id == "case_whitfield_afib":
        return {
            "summary": (
                "Stable new-onset AFib in [PATIENT_NAME_1] (68F, CKD3, on "
                "warfarin). Highest-priority issue is the proposed "
                "amiodarone-warfarin interaction. Rate control should be "
                "weighed against rhythm control as a guideline-aligned "
                "first step."
            ),
            "ranked_actions": [
                {
                    "action": "Reconsider amiodarone: prefer rate control with metoprolol or diltiazem first-line",
                    "rationale": "Amiodarone potentiates warfarin via CYP2C9/3A4; rate control is reasonable first-line per AFib guideline.",
                    "agents_supporting": ["pharmacy", "guidelines", "bias_check"],
                    "priority": "high",
                },
                {
                    "action": "If rhythm control remains essential, reduce warfarin dose 30-50% on day of amiodarone start and recheck INR q3-4 days for 2 weeks",
                    "rationale": "Expected INR rise to 4.5+ within 7-10 days without dose adjustment.",
                    "agents_supporting": ["pharmacy", "guidelines"],
                    "priority": "high",
                },
                {
                    "action": "Echocardiogram within 2 weeks",
                    "rationale": "Standard work-up for new-onset AF.",
                    "agents_supporting": ["differential", "guidelines"],
                    "priority": "med",
                },
                {
                    "action": "Cardiology follow-up scheduled with [PROVIDER_NAME_1] in 2 weeks",
                    "rationale": "Continuity of care.",
                    "agents_supporting": ["communication"],
                    "priority": "med",
                },
            ],
            "cross_flags": cross_flags,
            "patient_facing": (
                "[PATIENT_NAME_1], your heart is beating irregularly today, a "
                "condition we can treat safely. Before we add a new medicine, "
                "we want to make sure it works well with your current blood "
                "thinner. Your team will discuss the options with you. Please "
                "come back if you feel faint, very short of breath, or have "
                "chest pain."
            ),
        }
    if case_id == "case_singh_chest_pain":
        return {
            "summary": (
                "Likely pulmonary embolism in [PATIENT_NAME_1] (54M, recent "
                "10h flight). The chest pain observation pathway should be "
                "paused until CTPA is complete."
            ),
            "ranked_actions": [
                {
                    "action": "CT pulmonary angiogram immediately",
                    "rationale": "Pleuritic pain + hypoxia + elevated D-dimer + recent immobility.",
                    "agents_supporting": ["triage", "differential", "guidelines", "bias_check"],
                    "priority": "high",
                },
                {
                    "action": "Empirical therapeutic anticoagulation while imaging pending if no contraindication",
                    "rationale": "Standard PE-suspected management in hemodynamically stable patient.",
                    "agents_supporting": ["pharmacy", "guidelines"],
                    "priority": "high",
                },
                {
                    "action": "Hold further ACS escalation until PE ruled in/out",
                    "rationale": "Avoid premature closure.",
                    "agents_supporting": ["bias_check", "differential"],
                    "priority": "med",
                },
            ],
            "cross_flags": cross_flags,
            "patient_facing": (
                "[PATIENT_NAME_1], your symptoms and your recent long flight "
                "suggest a possible blood clot in the lung. We are arranging "
                "a special CT scan now. If confirmed, we will start a blood "
                "thinner. Please tell us if your breathing gets worse."
            ),
        }
    if case_id == "case_chen_headache":
        return {
            "summary": (
                "Thunderclap headache with meningismus in [PATIENT_NAME_1] "
                "(32F, OCP user). Subarachnoid hemorrhage and meningitis are "
                "the priority differentials; migraine label is unsafe "
                "without imaging."
            ),
            "ranked_actions": [
                {
                    "action": "Non-contrast CT head immediately",
                    "rationale": "Sensitivity for SAH ~100% within 6h of onset.",
                    "agents_supporting": ["triage", "differential", "guidelines", "bias_check"],
                    "priority": "high",
                },
                {
                    "action": "Hold ketorolac until intracranial hemorrhage excluded",
                    "rationale": "NSAID + possible SAH = harm.",
                    "agents_supporting": ["pharmacy", "guidelines"],
                    "priority": "high",
                },
                {
                    "action": "Lumbar puncture if CT negative and onset >6h",
                    "rationale": "Catches xanthochromia in late-presenting SAH.",
                    "agents_supporting": ["differential", "guidelines"],
                    "priority": "med",
                },
            ],
            "cross_flags": cross_flags,
            "patient_facing": (
                "[PATIENT_NAME_1], your sudden severe headache needs an "
                "urgent brain scan today before we treat the pain. There "
                "are a few serious causes we want to rule out first. We "
                "will not give you a pain shot that could cause harm if "
                "there is bleeding."
            ),
        }
    if case_id == "case_patel_falls":
        return {
            "summary": (
                "Likely iatrogenic cognitive decline and falls in "
                "[PATIENT_NAME_1] (76M) from very high anticholinergic + "
                "sedative load. Deprescribe before any dementia therapy."
            ),
            "ranked_actions": [
                {
                    "action": "Deprescribe anticholinergic and sedative agents (diphenhydramine, taper amitriptyline + lorazepam, swap oxybutynin to mirabegron)",
                    "rationale": "ACB ~11 fully explains the syndrome; expected reversible.",
                    "agents_supporting": ["pharmacy", "guidelines", "bias_check", "differential"],
                    "priority": "high",
                },
                {
                    "action": "Defer rivastigmine",
                    "rationale": "Adding cholinesterase inhibitor over strong anticholinergics is contradictory.",
                    "agents_supporting": ["pharmacy", "bias_check"],
                    "priority": "high",
                },
                {
                    "action": "Non-contrast CT head to rule out subdural hematoma",
                    "rationale": "Unwitnessed falls in older adult on no anticoagulant - still worth ruling out.",
                    "agents_supporting": ["differential"],
                    "priority": "med",
                },
                {
                    "action": "Reassess cognition in 6-8 weeks after deprescribing",
                    "rationale": "Standard window for anticholinergic washout.",
                    "agents_supporting": ["guidelines"],
                    "priority": "med",
                },
            ],
            "cross_flags": cross_flags,
            "patient_facing": (
                "[PATIENT_NAME_1], we believe some of your symptoms - the "
                "confusion, dry mouth, falls - are caused by your medicines "
                "working together. We want to safely stop or swap a few of "
                "them, then see how you feel in 6-8 weeks. Please do not "
                "stop any medicine on your own; your pharmacist will give "
                "you a clear plan."
            ),
        }
    return {
        "summary": "Insufficient structured input.",
        "ranked_actions": [],
        "cross_flags": cross_flags,
        "patient_facing": "Insufficient information.",
    }


async def run_orchestrator_simulated(
    *,
    case_id: str,
    specialist_outputs: dict[str, Any],
    on_token: Optional[TokenCallback],
) -> AgentResult:
    return await simulated_stream(
        name=NAME,
        output=_simulated_for_case(case_id, specialist_outputs),
        on_token=on_token,
        pause=0.003,
    )
