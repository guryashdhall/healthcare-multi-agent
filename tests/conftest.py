"""Test fixtures and path setup.

Adds the repo root to sys.path so tests can import the ``src`` package without
installing the project.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
