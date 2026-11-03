#!/usr/bin/env bash
# SessionStart hook: install project dependencies for the checked-out branch.
# Fast when nothing changed (uv and Bun reuse their caches).
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"
missing=""
command -v uv >/dev/null || missing="$missing uv"
command -v bun >/dev/null || missing="$missing bun"
if [ -n "$missing" ]; then
  echo "Mosaic: missing$missing. Run scripts/cloud-setup.sh (or install them) first." >&2
  exit 0
fi
uv sync --locked --quiet && bun install --frozen-lockfile --silent \
  && echo "Mosaic: dependencies ready (uv $(uv --version | cut -d' ' -f2), bun $(bun --version))."
exit 0
