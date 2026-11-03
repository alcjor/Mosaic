#!/usr/bin/env bash
# Setup script for the Claude Code cloud environment (paste into the
# environment's setup script field, or call it from there). It is cached,
# so it does not run on every session.
set -euo pipefail

# Python 3.14 and the uv workspace
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.14

# Node 22+ is expected on the image; install workspace dependencies
if [ -d mosaic ]; then cd mosaic; fi
uv sync --locked
npm ci

# Playwright browsers arrive with the viewer tests (M2):
# npx playwright install --with-deps chromium

# Conformance fixtures, pinned by hash (no-op until fixtures are listed)
uv run python scripts/fetch_fixtures.py
