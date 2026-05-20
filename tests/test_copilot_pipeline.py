"""End-to-end tests for run_copilot_streaming: agents see only de-identified
text; audit log never contains raw PHI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.pipeline import run_copilot_streaming


REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "data" / "cases"


_FORBIDDEN_RAW_PHI = [
    "Eleanor Whitfield",
    "NSH-907782",
    "902-555-0177",
    "Spring Garden Road",
    "Rajiv Singh",
    "NSH-441208",
    "Linh Chen",
    "Arvind Patel",
]


def _load(case_id: str) -> dict:
    return json.loads((CASES_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_copilot_hero_case_runs_end_to_end(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    events: list[dict] = []

    async def emit(evt):
        events.append(evt)

    case = _load("case_whitfield_afib")
    final = await run_copilot_streaming(
        case_id="case_whitfield_afib",
        case_json=case,
        engine="simulated",
        event_callback=emit,
        audit_log_path=audit_path,
    )
    assert final["status"] == "completed"
    assert final["agent_count"] == 7  # 6 specialists + orchestrator

    # Cross-flags must include the warfarin/amiodarone convergence.
    rehydration_events = [e for e in events if e["type"] == "rehydration"]
    assert rehydration_events, "no rehydration event emitted"
    orch = rehydration_events[-1]["data"]["rehydrated_orchestrator"]
    flag_blob = " ".join(f.get("flag", "") for f in orch.get("cross_flags", [])).lower()
    assert "amiodarone" in flag_blob or "warfarin" in flag_blob

    # Re-hydrated text should include the real synthetic patient name -
    # this is the wow moment showing the clinician gets the name back.
    rehydrated_text = json.dumps(orch)
    assert "Eleanor Whitfield" in rehydrated_text


@pytest.mark.asyncio
async def test_copilot_audit_log_contains_no_raw_phi(tmp_path):
    """Run the co-pilot on every preset case and assert the audit JSONL
    contains zero raw PHI strings - the security promise still holds."""
    audit_path = tmp_path / "audit.jsonl"
    for cid in (
        "case_whitfield_afib",
        "case_singh_chest_pain",
        "case_chen_headache",
        "case_patel_falls",
    ):
        case = _load(cid)
        await run_copilot_streaming(
            case_id=cid,
            case_json=case,
            engine="simulated",
            event_callback=None,
            audit_log_path=audit_path,
        )

    contents = audit_path.read_text(encoding="utf-8")
    for needle in _FORBIDDEN_RAW_PHI:
        assert needle not in contents, (
            f"audit log leaked raw PHI: {needle!r}"
        )

    # And every event should be valid JSON.
    for line in contents.splitlines():
        line = line.strip()
        if line:
            payload = json.loads(line)
            assert payload["pipeline_status"] == "completed"


@pytest.mark.asyncio
async def test_copilot_agents_never_receive_raw_phi(tmp_path):
    """Capture the de-identified text sent to agents and verify no raw PHI
    strings are present in it."""
    captured_deid_text: list[str] = []

    async def emit(evt):
        if evt["type"] == "stage_end" and evt.get("stage") == "redaction":
            captured_deid_text.append(evt["data"]["deidentified_text"])

    case = _load("case_whitfield_afib")
    await run_copilot_streaming(
        case_id="case_whitfield_afib",
        case_json=case,
        engine="simulated",
        event_callback=emit,
        audit_log_path=tmp_path / "audit.jsonl",
    )
    assert captured_deid_text, "redaction event never emitted"
    deid = captured_deid_text[0]
    assert "Eleanor Whitfield" not in deid
    assert "NSH-907782" not in deid
    assert "902-555-0177" not in deid
    # Placeholders should be present.
    assert "[PATIENT_NAME_" in deid
    assert "[MRN_" in deid
