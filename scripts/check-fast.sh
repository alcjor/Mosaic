#!/usr/bin/env bash
# The fast local gate: what every change must pass before it is handed back.
# CI runs the same checks on Linux.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check
uv run --locked lint-imports
uv run --locked pytest -m "not slow"
npm run --silent typecheck
npm run --silent test
