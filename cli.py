"""CLI entrypoint.

Runs the PHI-safe pipeline against every synthetic note in data/raw/ and
prints a per-note console report.

Usage:
    python cli.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``src`` importable when the script is run directly from the repo.
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import AUDIT_LOG_PATH, PROCESSED_DIR, SAMPLE_NOTES  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402
from src.reporting.console_reporter import (  # noqa: E402
    render_footer,
    render_header,
    render_result,
)


def _reset_outputs() -> None:
    """Wipe previous outputs so each run is clean."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.unlink()
    for path in PROCESSED_DIR.glob("*.deidentified.txt"):
        path.unlink()
    for path in PROCESSED_DIR.glob("*.summary.json"):
        path.unlink()


def main() -> int:
    _reset_outputs()

    print(render_header())

    completed = 0
    blocked = 0
    for name in SAMPLE_NOTES:
        result = run_pipeline(name)
        print()
        print(render_result(result))
        if result.status == "completed":
            completed += 1
        else:
            blocked += 1

    print()
    print("-" * 78)
    print(f"Notes processed : {len(SAMPLE_NOTES)}")
    print(f"Completed       : {completed}")
    print(f"Blocked         : {blocked}")
    print(f"Audit log       : {AUDIT_LOG_PATH}")
    print(render_footer())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
