"""Tests for the PHI detector."""

from __future__ import annotations

from src.deid.detector import detect_phi


SAMPLE = (
    "Patient: Sarah Mitchell\n"
    "DOB: 1974-03-18\n"
    "MRN: NSH-882391\n"
    "Phone: 902-555-0192\n"
    "Email: sarah.mitchell@example.com\n"
    "Address: 145 Queen Street, Halifax, NS B3J 2H7\n"
    "Health Card: NS-1234-567-890\n"
    "Provider: Dr. James Carter\n"
    "Follow-up: May 4, 2026\n"
)


def _types(entities) -> set[str]:
    return {e.entity_type for e in entities}


def test_detects_all_expected_categories():
    entities = detect_phi(SAMPLE)
    found = _types(entities)
    expected = {
        "PATIENT_NAME",
        "DOB",
        "MRN",
        "PHONE",
        "EMAIL",
        "ADDRESS",
        "HEALTH_CARD",
        "PROVIDER_NAME",
        "DATE",
        "POSTAL_CODE",
    }
    missing = expected - found
    assert not missing, f"detector missed categories: {missing}"


def test_returns_indices_that_round_trip():
    entities = detect_phi(SAMPLE)
    for entity in entities:
        assert (
            SAMPLE[entity.start_index : entity.end_index] == entity.matched_text
        )


def test_safe_text_yields_no_high_risk_entities():
    text = (
        "Patient is a middle-aged adult with stable asthma. No new symptoms.\n"
        "Continue current inhaled corticosteroid. Routine follow-up in three months.\n"
    )
    entities = detect_phi(text)
    high_risk = {"MRN", "PHONE", "EMAIL", "HEALTH_CARD", "PATIENT_NAME"}
    found = _types(entities)
    assert not (found & high_risk)
