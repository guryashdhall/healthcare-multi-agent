#!/usr/bin/env bash
# Launches the FastAPI web app on http://localhost:8765
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

exec ./.venv/bin/uvicorn web.main:app --reload --port 8765 --host 0.0.0.0
