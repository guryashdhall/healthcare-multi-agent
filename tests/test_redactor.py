"""Tests for the deterministic redactor."""

from __future__ import annotations

import re

from src.deid.detector import detect_phi
from src.deid.redactor import redact


def test_replaces_phi_with_placeholders():
    text = "Patient: Sarah Mitchell\nProvider: Dr. James Carter\n"
    entities = detect_phi(text)
    result = redact(text, entities)

    assert "Sarah Mitchell" not in result.deidentified_text
    assert "Dr. James Carter" not in result.deidentified_text
    assert "[PATIENT_NAME_1]" in result.deidentified_text
    assert "[PROVIDER_NAME_1]" in result.deidentified_text


def test_same_surface_gets_same_placeholder():
    text = (
        "Provider: Dr. James Carter\n"
        "Plan: Follow up with Dr. James Carter in one week.\n"
    )
    entities = detect_phi(text)
    result = redact(text, entities)

    placeholders = re.findall(r"\[PROVIDER_NAME_\d+\]", result.deidentified_text)
    assert len(placeholders) == 2
    assert placeholders[0] == placeholders[1]


def test_distinct_surfaces_get_distinct_placeholders():
    text = "Provider: Dr. James Carter\nConsulting: Dr. Lisa Nguyen\n"
    entities = detect_phi(text)
    result = redact(text, entities)

    placeholders = sorted(set(re.findall(r"\[PROVIDER_NAME_\d+\]", result.deidentified_text)))
    assert placeholders == ["[PROVIDER_NAME_1]", "[PROVIDER_NAME_2]"]


def test_entity_counts_returned():
    text = "Phone: 902-555-0192\nEmail: a@b.co\n"
    entities = detect_phi(text)
    result = redact(text, entities)
    assert result.entity_counts.get("PHONE") == 1
    assert result.entity_counts.get("EMAIL") == 1
