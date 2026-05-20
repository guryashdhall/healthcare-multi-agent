"""Tests that audit logs never carry raw PHI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.audit.audit_logger import AuditEvent, AuditLogger
from src.pipeline import run_pipeline


REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"


# Strings we know appear in the synthetic notes that must NEVER appear in the
# audit log file.
_FORBIDDEN_RAW_PHI = [
    "Sarah Mitchell",
    "sarah.mitchell@example.com",
    "902-555-0192",
    "NSH-882391",
    "NS-1234-567-890",
    "James Carter",
    "Michael Thompson",
    "Eleanor Whitfield",
    "Spring Garden Road",
    "Queen Street",
]


@pytest.fixture()
def isolated(tmp_path):
    raw_copy = tmp_path / "raw"
    raw_copy.mkdir()
    for note in RAW_DIR.glob("*.txt"):
        shutil.copy(note, raw_copy / note.name)
    audit_path = tmp_path / "audit.jsonl"
    return raw_copy, audit_path


def test_audit_log_contains_no_raw_phi(isolated):
    raw_copy, audit_path = isolated
    for name in [
        "note_safe.txt",
        "note_with_phi.txt",
        "note_with_prompt_injection.txt",
        "note_complex.txt",
    ]:
        run_pipeline(
            name,
            raw_dir=raw_copy,
            audit_log_path=audit_path,
            write_outputs=False,
        )

    contents = audit_path.read_text(encoding="utf-8")
    for needle in _FORBIDDEN_RAW_PHI:
        assert needle not in contents, f"audit log leaked raw PHI: {needle!r}"


def test_audit_lines_are_valid_json_with_required_fields(isolated):
    raw_copy, audit_path = isolated
    run_pipeline(
        "note_with_phi.txt",
        raw_dir=raw_copy,
        audit_log_path=audit_path,
        write_outputs=False,
    )
    lines = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines, "audit log should have at least one event"
    event = lines[-1]
    required = {
        "timestamp_utc",
        "source_file",
        "pipeline_status",
        "phi_detected_counts",
        "deidentification_status",
        "phi_validation_status",
        "prompt_injection_status",
        "summarization_status",
        "raw_input_sha256",
    }
    missing = required - set(event)
    assert not missing, f"audit event missing fields: {missing}"
    # SHA-256 hex strings are 64 chars long.
    assert len(event["raw_input_sha256"]) == 64


def test_blocked_events_record_blocked_reason(isolated):
    raw_copy, audit_path = isolated
    run_pipeline(
        "note_with_prompt_injection.txt",
        raw_dir=raw_copy,
        audit_log_path=audit_path,
        write_outputs=False,
    )
    event = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["pipeline_status"] == "blocked"
    assert event["blocked_reason"]
    assert "prompt_injection_detected" in event["blocked_reason"]


def test_audit_logger_writes_jsonl(tmp_path):
    path = tmp_path / "log.jsonl"
    logger = AuditLogger(path)
    logger.write(
        AuditEvent(
            timestamp_utc="2026-05-03T00:00:00Z",
            source_file="x.txt",
            pipeline_status="completed",
            phi_detected_counts={"EMAIL": 1},
            deidentification_status="completed",
            phi_validation_status="passed",
            prompt_injection_status="passed",
            summarization_status="completed",
            raw_input_sha256="a" * 64,
        )
    )
    line = path.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["pipeline_status"] == "completed"
    assert parsed["phi_detected_counts"] == {"EMAIL": 1}
