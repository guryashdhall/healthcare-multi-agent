"""Configuration constants for the pipeline.

All paths are resolved relative to the repository root so the application
can be run from any working directory.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = REPO_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
PROCESSED_DIR: Path = DATA_DIR / "processed"

AUDIT_LOG_PATH: Path = PROCESSED_DIR / "audit_log.jsonl"

SAMPLE_NOTES: tuple[str, ...] = (
    "note_safe.txt",
    "note_with_phi.txt",
    "note_with_prompt_injection.txt",
    "note_complex.txt",
)

DISCLAIMER: str = (
    "This application uses privacy-preserving engineering patterns over "
    "synthetic data only. It is NOT a HIPAA/PHIPA-compliant system and "
    "must not be used with real patient data."
)
