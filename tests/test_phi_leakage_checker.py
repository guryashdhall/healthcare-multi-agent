"""Tests for the PHI leakage validator."""

from __future__ import annotations

from src.validation.phi_leakage_checker import check_phi_leakage


def test_clean_deidentified_text_passes():
    text = (
        "Patient: [PATIENT_NAME_1]\n"
        "Provider: [PROVIDER_NAME_1]\n"
        "Follow-up: [DATE_1]\n"
        "Patient presents with worsening dyspnea and chest tightness.\n"
    )
    result = check_phi_leakage(text)
    assert result.passed is True
    assert result.leakage_findings == []


def test_phone_leakage_detected():
    text = "Patient: [PATIENT_NAME_1]\nContact: 902-555-0192\n"
    result = check_phi_leakage(text)
    assert result.passed is False
    assert any(f.category == "PHONE" for f in result.leakage_findings)


def test_email_leakage_detected():
    text = "Patient: [PATIENT_NAME_1]\nEmail: a@b.com\n"
    result = check_phi_leakage(text)
    assert result.passed is False
    assert any(f.category == "EMAIL" for f in result.leakage_findings)


def test_residual_patient_name_detected():
    text = "Patient: Sarah Mitchell\n"
    result = check_phi_leakage(text)
    assert result.passed is False
    assert any(
        f.category == "PATIENT_NAME_AFTER_LABEL" for f in result.leakage_findings
    )


def test_finding_preview_is_masked():
    text = "Patient: [PATIENT_NAME_1]\nMRN: NSH-882391\n"
    result = check_phi_leakage(text)
    assert result.passed is False
    finding = next(f for f in result.leakage_findings if f.category == "MRN")
    preview = finding.as_dict()["preview"]
    assert "NSH-882391" not in preview
    assert "*" in preview
