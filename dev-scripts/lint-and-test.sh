#!/usr/bin/env bash
# ruff + pytest — the local CI equivalent.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> ruff"
.venv/bin/ruff check .

echo "==> pytest"
.venv/bin/pytest -q

echo "All checks passed."
