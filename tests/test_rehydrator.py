"""Tests for the re-hydration stage."""

from __future__ import annotations

from src.deid.detector import detect_phi
from src.deid.redactor import redact
from src.deid.rehydrator import rehydrate


def test_round_trip_restores_original_phi():
    raw = (
        "Patient: Sarah Mitchell\n"
        "Provider: Dr. James Carter\n"
        "Plan: Follow up with Dr. James Carter in one week.\n"
    )
    entities = detect_phi(raw)
    redaction = redact(raw, entities)

    fake_llm_summary = {
        "summary_type": "clinical_workflow_support",
        "chief_concern": "Routine follow-up",
        "follow_up_questions": [
            "Has [PATIENT_NAME_1] been adherent to therapy?",
            "Confirm next visit with [PROVIDER_NAME_1].",
        ],
        "source_text_status": "deidentified",
    }

    result = rehydrate(fake_llm_summary, redaction.replacement_map)

    rehydrated = result.rehydrated_summary
    assert "Sarah Mitchell" in rehydrated["follow_up_questions"][0]
    assert "Dr. James Carter" in rehydrated["follow_up_questions"][1]
    assert result.placeholders_replaced.get("PATIENT_NAME_1") == 1
    assert result.placeholders_replaced.get("PROVIDER_NAME_1") == 1
    assert result.unresolved_placeholders == []


def test_invented_placeholder_is_left_intact_and_reported():
    replacement_map = {"Sarah Mitchell": "[PATIENT_NAME_1]"}
    summary = {
        "chief_concern": "Routine follow-up",
        "notes": [
            "Confirm contact info for [PATIENT_NAME_1].",
            "Verify provider [PROVIDER_NAME_42] availability.",
        ],
    }

    result = rehydrate(summary, replacement_map)

    assert result.rehydrated_summary["notes"][0] == "Confirm contact info for Sarah Mitchell."
    # The invented placeholder is preserved verbatim for clinician review.
    assert "[PROVIDER_NAME_42]" in result.rehydrated_summary["notes"][1]
    assert "PROVIDER_NAME_42" in result.unresolved_placeholders
    assert result.placeholders_replaced.get("PATIENT_NAME_1") == 1
