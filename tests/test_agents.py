"""Tests for the multi-agent co-pilot."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.agents import (
    bias_check,
    communication,
    copilot_runner,
    differential,
    guidelines,
    orchestrator,
    pharmacy,
    triage,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "data" / "cases"


def _load_case(name: str) -> dict:
    return json.loads((CASES_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_pharmacy_catches_warfarin_amiodarone():
    """The hero-case Pharmacy agent must flag the warfarin/amiodarone
    interaction. This is the demo's keystone moment."""
    result = await pharmacy.run_pharmacy_simulated(
        case_id="case_whitfield_afib", on_token=None
    )
    text = json.dumps(result.output).lower()
    assert "warfarin" in text
    assert "amiodarone" in text
    high = [i for i in result.output.get("interactions", []) if i.get("severity") == "high"]
    assert any("warfarin" in str(i).lower() and "amiodarone" in str(i).lower() for i in high), (
        "Pharmacy agent failed to flag warfarin/amiodarone as a high-severity interaction"
    )


@pytest.mark.asyncio
async def test_all_simulated_specialists_return_required_keys():
    fns = {
        "triage": triage.run_triage_simulated,
        "differential": differential.run_differential_simulated,
        "pharmacy": pharmacy.run_pharmacy_simulated,
        "guidelines": guidelines.run_guidelines_simulated,
        "bias_check": bias_check.run_bias_check_simulated,
        "communication": communication.run_communication_simulated,
    }
    for name, fn in fns.items():
        result = await fn(case_id="case_whitfield_afib", on_token=None)
        assert result.output, f"{name} returned empty output"
        assert result.error is None, f"{name} had error: {result.error}"


@pytest.mark.asyncio
async def test_copilot_fanout_runs_all_six_in_parallel():
    case = _load_case("case_whitfield_afib.json")
    deid_json = json.dumps(case)  # tests don't go through redact for simplicity
    results = await copilot_runner.run_all(
        case_id="case_whitfield_afib",
        deidentified_case_json=deid_json,
        engine="simulated",
        emit=None,
        per_agent_timeout=5.0,
    )
    for n in copilot_runner.SPECIALIST_NAMES:
        assert n in results, f"missing {n}"
        assert results[n].output, f"{n} returned no output"
    assert "orchestrator" in results
    orch = results["orchestrator"].output
    assert orch.get("ranked_actions"), "orchestrator produced no ranked actions"
    cross_flags = orch.get("cross_flags", [])
    flag_text = " ".join(f.get("flag", "") for f in cross_flags).lower()
    assert "amiodarone" in flag_text or "warfarin" in flag_text, (
        "Cross-flag system did not detect the warfarin/amiodarone convergence"
    )


@pytest.mark.asyncio
async def test_one_failing_agent_does_not_kill_others(monkeypatch):
    """If one agent raises, the others should still complete."""

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated agent failure")

    monkeypatch.setattr(pharmacy, "run_pharmacy_simulated", boom)
    case = _load_case("case_whitfield_afib.json")
    results = await copilot_runner.run_all(
        case_id="case_whitfield_afib",
        deidentified_case_json=json.dumps(case),
        engine="simulated",
        emit=None,
        per_agent_timeout=5.0,
    )
    assert results["pharmacy"].error, "expected pharmacy to error"
    for n in copilot_runner.SPECIALIST_NAMES:
        if n == "pharmacy":
            continue
        assert results[n].output, f"{n} should have completed despite pharmacy failure"


@pytest.mark.asyncio
async def test_copilot_streams_events():
    """Smoke: emit callback receives the expected event types."""
    events: list[dict] = []

    async def emit(evt):
        events.append(evt)

    case = _load_case("case_whitfield_afib.json")
    await copilot_runner.run_all(
        case_id="case_whitfield_afib",
        deidentified_case_json=json.dumps(case),
        engine="simulated",
        emit=emit,
        per_agent_timeout=5.0,
    )
    types = {e["type"] for e in events}
    assert "agent_start" in types
    assert "agent_token" in types
    assert "agent_final" in types
    # All seven agents (6 specialists + orchestrator) should have at least
    # one agent_start.
    starts = [e for e in events if e["type"] == "agent_start"]
    started_names = {e["data"]["name"] for e in starts}
    assert started_names == {*copilot_runner.SPECIALIST_NAMES, "orchestrator"}
