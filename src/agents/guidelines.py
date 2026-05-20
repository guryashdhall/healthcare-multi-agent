"""Guidelines specialist agent.

Cites the synthetic guideline corpus by ID + version. The full corpus is
included inline in the prompt so this is a self-contained retrieval-free
specialist for the demo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .base import AgentResult, TokenCallback, call_azure_streaming, simulated_stream


NAME = "guidelines"
DISPLAY = "Guidelines"
ICON = "GLN"

_GUIDELINES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "guidelines"
)


def load_guideline_corpus() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if not _GUIDELINES_DIR.exists():
        return docs
    for path in sorted(_GUIDELINES_DIR.glob("*.json")):
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return docs


def _system_prompt(corpus: list[dict[str, Any]]) -> str:
    return (
        "You are a clinical guidelines specialist. Below is a small "
        "guideline corpus (synthetic for demo). Identify which guidelines "
        "apply to the input case and quote the most relevant key "
        "recommendations. Respond with a single JSON object only:\n"
        "{"
        '"applicable": ['
        '  {"guideline_id": string, "version": string, '
        '   "key_recommendation": string, "why_relevant": string}'
        "], "
        '"caveats": [string]'
        "}\n"
        "Only use IDs from the corpus. Prefer 2-4 most relevant guidelines.\n\n"
        "GUIDELINE CORPUS:\n"
        + json.dumps(corpus, indent=2)
    )


async def run_guidelines_azure(
    *,
    deidentified_case_json: str,
    on_token: Optional[TokenCallback],
    timeout: float = 18.0,
) -> AgentResult:
    corpus = load_guideline_corpus()
    return await call_azure_streaming(
        name=NAME,
        system_prompt=_system_prompt(corpus),
        user_prompt=deidentified_case_json,
        on_token=on_token,
        timeout=timeout,
    )


def _simulated_for_case(case_id: str) -> dict[str, Any]:
    if case_id == "case_whitfield_afib":
        return {
            "applicable": [
                {
                    "guideline_id": "afib_management",
                    "version": "2024.2",
                    "key_recommendation": (
                        "In stable patients with new-onset AF, rate control is "
                        "reasonable first-line. Rhythm control reserved for "
                        "symptomatic patients despite rate control."
                    ),
                    "why_relevant": "Patient is hemodynamically stable - rate control should be considered before committing to amiodarone.",
                },
                {
                    "guideline_id": "warfarin_interactions",
                    "version": "2023.4",
                    "key_recommendation": (
                        "Amiodarone potentiates warfarin via CYP2C9 and "
                        "CYP3A4 inhibition. Reduce warfarin dose 30-50% "
                        "pre-emptively or monitor INR every 3-4 days."
                    ),
                    "why_relevant": "Critical to the proposed treatment plan.",
                },
                {
                    "guideline_id": "anticoagulation_afib",
                    "version": "2024.1",
                    "key_recommendation": (
                        "DOACs are preferred over warfarin in non-valvular AF "
                        "except mechanical valves or severe renal impairment."
                    ),
                    "why_relevant": "Could simplify anticoagulation if amiodarone interaction continues to be a problem.",
                },
            ],
            "caveats": [
                "Synthetic guideline corpus for demo only; verify against current AHA/ACC/ESC guidance.",
            ],
        }
    if case_id == "case_singh_chest_pain":
        return {
            "applicable": [
                {
                    "guideline_id": "chest_pain_workup",
                    "version": "2024.0",
                    "key_recommendation": (
                        "Use structured pretest probability (Wells/PERC) BEFORE "
                        "committing to ACS pathway. Pleuritic + hypoxia + "
                        "elevated D-dimer + recent immobilization = CTPA."
                    ),
                    "why_relevant": "Patient profile maps directly to PE pathway, not ACS-first.",
                },
            ],
            "caveats": [
                "Troponin elevation does not exclude PE (right heart strain).",
            ],
        }
    if case_id == "case_chen_headache":
        return {
            "applicable": [
                {
                    "guideline_id": "headache_red_flags",
                    "version": "2023.3",
                    "key_recommendation": (
                        "Thunderclap headache requires urgent non-contrast CT "
                        "head. If negative within 6h of onset, sensitivity "
                        "for SAH approaches 100%. LP if CT negative."
                    ),
                    "why_relevant": "Patient meets thunderclap criteria - imaging precedes analgesia.",
                },
            ],
            "caveats": ["OCP use + severe headache raises CVST in the differential."],
        }
    if case_id == "case_patel_falls":
        return {
            "applicable": [
                {
                    "guideline_id": "polypharmacy_elderly",
                    "version": "2024.1",
                    "key_recommendation": (
                        "ACB score >=3 is associated with cognitive impairment "
                        "and falls. Before adding symptomatic therapy, "
                        "deprescribe anticholinergic and sedating medications "
                        "and reassess in 6-8 weeks."
                    ),
                    "why_relevant": "Patient has ACB ~11 across five drugs; cognitive decline likely reversible.",
                },
                {
                    "guideline_id": "ckd_drug_dosing",
                    "version": "2024.0",
                    "key_recommendation": "HCTZ less effective at eGFR <60; reconsider antihypertensive.",
                    "why_relevant": "Patient eGFR 52 contributes to orthostatic hypotension.",
                },
            ],
            "caveats": ["Beers Criteria 2023 directly flags this medication list."],
        }
    return {
        "applicable": [],
        "caveats": ["No structured case provided; cannot map to guidelines."],
    }


async def run_guidelines_simulated(
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
