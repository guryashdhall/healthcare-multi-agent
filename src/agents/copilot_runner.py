"""Fan-out / fan-in coordinator for the six specialists + orchestrator."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from . import (
    bias_check,
    communication,
    differential,
    guidelines,
    orchestrator,
    pharmacy,
    triage,
)
from .base import AgentResult, TokenCallback


# Order matters only for display - all six run in parallel.
SPECIALIST_NAMES: list[str] = [
    triage.NAME,
    differential.NAME,
    pharmacy.NAME,
    guidelines.NAME,
    bias_check.NAME,
    communication.NAME,
]

DISPLAY_BY_NAME: dict[str, dict[str, str]] = {
    triage.NAME:        {"display": triage.DISPLAY,        "icon": triage.ICON},
    differential.NAME:  {"display": differential.DISPLAY,  "icon": differential.ICON},
    pharmacy.NAME:      {"display": pharmacy.DISPLAY,      "icon": pharmacy.ICON},
    guidelines.NAME:    {"display": guidelines.DISPLAY,    "icon": guidelines.ICON},
    bias_check.NAME:    {"display": bias_check.DISPLAY,    "icon": bias_check.ICON},
    communication.NAME: {"display": communication.DISPLAY, "icon": communication.ICON},
    orchestrator.NAME:  {"display": orchestrator.DISPLAY,  "icon": orchestrator.ICON},
}


EmitEvent = Callable[[dict[str, Any]], Awaitable[None]]


def _user_prompt_for_case(deidentified_case_json: str) -> str:
    return (
        "Below is the de-identified clinical case as JSON. Reason only from "
        "this content; do not invent facts.\n\n"
        f"{deidentified_case_json}"
    )


async def _emit(emit: Optional[EmitEvent], event: dict[str, Any]) -> None:
    if emit is not None:
        await emit(event)


async def _run_one_specialist(
    *,
    name: str,
    case_id: str,
    deidentified_case_json: str,
    engine: str,  # "azure_openai" | "simulated"
    on_token: TokenCallback,
    emit: Optional[EmitEvent],
) -> AgentResult:
    await _emit(emit, {"type": "agent_start", "data": {"name": name}})
    user_prompt = _user_prompt_for_case(deidentified_case_json)
    try:
        if engine == "simulated":
            if name == triage.NAME:
                result = await triage.run_triage_simulated(case_id=case_id, on_token=on_token)
            elif name == differential.NAME:
                result = await differential.run_differential_simulated(case_id=case_id, on_token=on_token)
            elif name == pharmacy.NAME:
                result = await pharmacy.run_pharmacy_simulated(case_id=case_id, on_token=on_token)
            elif name == guidelines.NAME:
                result = await guidelines.run_guidelines_simulated(case_id=case_id, on_token=on_token)
            elif name == bias_check.NAME:
                result = await bias_check.run_bias_check_simulated(case_id=case_id, on_token=on_token)
            elif name == communication.NAME:
                result = await communication.run_communication_simulated(case_id=case_id, on_token=on_token)
            else:
                raise ValueError(f"unknown specialist {name}")
        else:
            if name == triage.NAME:
                result = await triage.run_triage_azure(
                    deidentified_case_json=user_prompt, on_token=on_token
                )
            elif name == differential.NAME:
                result = await differential.run_differential_azure(
                    deidentified_case_json=user_prompt, on_token=on_token
                )
            elif name == pharmacy.NAME:
                result = await pharmacy.run_pharmacy_azure(
                    deidentified_case_json=user_prompt, on_token=on_token
                )
            elif name == guidelines.NAME:
                result = await guidelines.run_guidelines_azure(
                    deidentified_case_json=user_prompt, on_token=on_token
                )
            elif name == bias_check.NAME:
                result = await bias_check.run_bias_check_azure(
                    deidentified_case_json=user_prompt, on_token=on_token
                )
            elif name == communication.NAME:
                result = await communication.run_communication_azure(
                    deidentified_case_json=user_prompt, on_token=on_token
                )
            else:
                raise ValueError(f"unknown specialist {name}")

            # If Azure failed for any reason, fall back to simulated so the
            # UI never goes blank.
            if result.error or not result.output:
                fallback = await _run_one_specialist(
                    name=name,
                    case_id=case_id,
                    deidentified_case_json=deidentified_case_json,
                    engine="simulated",
                    on_token=on_token,
                    emit=None,
                )
                fallback.source = "fallback_local"
                fallback.error = result.error
                result = fallback
    except Exception as exc:  # noqa: BLE001
        # Last-resort safety net.
        await _emit(
            emit,
            {
                "type": "agent_final",
                "data": {
                    "name": name,
                    "output": {},
                    "source": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_ms": 0,
                },
            },
        )
        return AgentResult(name=name, error=f"{type(exc).__name__}: {exc}")

    await _emit(
        emit,
        {
            "type": "agent_final",
            "data": {
                "name": result.name,
                "output": result.output,
                "source": result.source,
                "error": result.error,
                "elapsed_ms": result.elapsed_ms,
            },
        },
    )
    return result


async def run_all(
    *,
    case_id: str,
    deidentified_case_json: str,
    engine: str = "azure_openai",
    emit: Optional[EmitEvent] = None,
    per_agent_timeout: float = 20.0,
) -> dict[str, AgentResult]:
    """Run all six specialists in parallel, then the orchestrator."""

    async def on_token(agent_name: str, delta: str) -> None:
        await _emit(
            emit,
            {"type": "agent_token", "data": {"name": agent_name, "delta": delta}},
        )

    tasks = [
        asyncio.create_task(
            asyncio.wait_for(
                _run_one_specialist(
                    name=n,
                    case_id=case_id,
                    deidentified_case_json=deidentified_case_json,
                    engine=engine,
                    on_token=on_token,
                    emit=emit,
                ),
                timeout=per_agent_timeout,
            ),
            name=f"agent_{n}",
        )
        for n in SPECIALIST_NAMES
    ]
    results: dict[str, AgentResult] = {}
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    for n, r in zip(SPECIALIST_NAMES, raw_results):
        if isinstance(r, Exception):
            results[n] = AgentResult(name=n, error=f"{type(r).__name__}: {r}")
            await _emit(
                emit,
                {
                    "type": "agent_final",
                    "data": {
                        "name": n,
                        "output": {},
                        "source": "error",
                        "error": str(r),
                        "elapsed_ms": 0,
                    },
                },
            )
        else:
            results[n] = r

    # Orchestrator runs after the others - it needs their outputs.
    specialist_outputs = {n: r.output for n, r in results.items()}
    await _emit(emit, {"type": "agent_start", "data": {"name": orchestrator.NAME}})

    if engine == "simulated":
        orch_result = await orchestrator.run_orchestrator_simulated(
            case_id=case_id,
            specialist_outputs=specialist_outputs,
            on_token=on_token,
        )
    else:
        try:
            orch_result = await asyncio.wait_for(
                orchestrator.run_orchestrator_azure(
                    specialist_outputs=specialist_outputs,
                    on_token=on_token,
                ),
                timeout=per_agent_timeout + 5,
            )
        except asyncio.TimeoutError:
            orch_result = AgentResult(name=orchestrator.NAME, error="timeout")

        if orch_result.error or not orch_result.output:
            fb = await orchestrator.run_orchestrator_simulated(
                case_id=case_id,
                specialist_outputs=specialist_outputs,
                on_token=on_token,
            )
            fb.source = "fallback_local"
            fb.error = orch_result.error
            orch_result = fb

    results[orchestrator.NAME] = orch_result
    await _emit(
        emit,
        {
            "type": "agent_final",
            "data": {
                "name": orch_result.name,
                "output": orch_result.output,
                "source": orch_result.source,
                "error": orch_result.error,
                "elapsed_ms": orch_result.elapsed_ms,
            },
        },
    )

    return results
