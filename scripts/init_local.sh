#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

python scripts/bootstrap.py
etf db-init
etf doctor

echo
echo "Initialization complete."
echo "Try:"
echo "  source .venv/bin/activate"
echo "  etf sync-quotes"
echo "  etf sync-shares"
echo "  etf api"
