"""End-to-end pipeline tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.pipeline import run_pipeline


REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"


@pytest.fixture()
def isolated_run(tmp_path):
    """Provide a fresh raw_dir + audit_log_path for each test."""
    raw_copy = tmp_path / "raw"
    raw_copy.mkdir()
    for note in RAW_DIR.glob("*.txt"):
        shutil.copy(note, raw_copy / note.name)
    audit_path = tmp_path / "audit.jsonl"
    return raw_copy, audit_path


def test_safe_note_completes(isolated_run):
    raw_copy, audit_path = isolated_run
    result = run_pipeline(
        "note_safe.txt",
        raw_dir=raw_copy,
        audit_log_path=audit_path,
        write_outputs=False,
    )
    assert result.status == "completed"
    assert result.blocked_reason is None
    assert result.validation_result["passed"] is True
    assert result.prompt_injection_result["passed"] is True
    assert result.summary is not None
    assert result.summary["source_text_status"] == "deidentified"


def test_phi_note_completes_after_deidentification(isolated_run):
    raw_copy, audit_path = isolated_run
    result = run_pipeline(
        "note_with_phi.txt",
        raw_dir=raw_copy,
        audit_log_path=audit_path,
        write_outputs=False,
    )
    assert result.status == "completed"
    assert result.phi_detected_counts.get("PATIENT_NAME", 0) >= 1
    assert result.phi_detected_counts.get("MRN", 0) >= 1
    assert result.validation_result["passed"] is True


def test_prompt_injection_note_blocked(isolated_run):
    raw_copy, audit_path = isolated_run
    result = run_pipeline(
        "note_with_prompt_injection.txt",
        raw_dir=raw_copy,
        audit_log_path=audit_path,
        write_outputs=False,
    )
    assert result.status == "blocked"
    assert result.blocked_reason is not None
    assert "prompt_injection_detected" in result.blocked_reason
    assert result.summary is None


def test_complex_note_completes(isolated_run):
    raw_copy, audit_path = isolated_run
    result = run_pipeline(
        "note_complex.txt",
        raw_dir=raw_copy,
        audit_log_path=audit_path,
        write_outputs=False,
    )
    assert result.status == "completed"
    assert result.phi_detected_counts.get("PROVIDER_NAME", 0) >= 2
    assert result.validation_result["passed"] is True


def test_pipeline_writes_outputs_when_requested(tmp_path, monkeypatch):
    """Outputs land in data/processed and audit log gets a valid JSON line."""
    from src import config as cfg

    raw_copy = tmp_path / "raw"
    raw_copy.mkdir()
    for note in RAW_DIR.glob("*.txt"):
        shutil.copy(note, raw_copy / note.name)
    processed = tmp_path / "processed"
    audit_path = processed / "audit.jsonl"

    monkeypatch.setattr(cfg, "PROCESSED_DIR", processed)
    monkeypatch.setattr(cfg, "RAW_DIR", raw_copy)
    monkeypatch.setattr(cfg, "AUDIT_LOG_PATH", audit_path)
    # Pipeline imports the symbols by name - patch them in the pipeline module too.
    from src import pipeline as pl

    monkeypatch.setattr(pl, "PROCESSED_DIR", processed)
    monkeypatch.setattr(pl, "RAW_DIR", raw_copy)
    monkeypatch.setattr(pl, "AUDIT_LOG_PATH", audit_path)

    result = run_pipeline(
        "note_with_phi.txt",
        raw_dir=raw_copy,
        audit_log_path=audit_path,
        write_outputs=True,
    )
    assert result.status == "completed"
    assert result.deidentified_text_path is not None
    assert Path(result.deidentified_text_path).exists()
    assert result.summary_path is not None
    summary_payload = json.loads(Path(result.summary_path).read_text())
    assert summary_payload["source_text_status"] == "deidentified"
