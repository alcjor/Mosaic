#!/usr/bin/env bash
# Toolchain for Claude Code cloud sessions on Mosaic.
# Paste into the cloud environment's setup script (or curl it from the repo).
# It installs tools only; project dependencies are installed per session by the
# SessionStart hook (.claude/hooks/session-start.sh), so they always match the branch.
set -euo pipefail

UV_VERSION="0.11.32"
BUN_VERSION="1.4.4"
PYTHON_VERSION="3.14"

export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"

# uv: from PyPI (package registries are reachable from cloud environments)
if ! command -v uv >/dev/null; then
  python3 -m pip install --user --break-system-packages "uv==$UV_VERSION" \
    || curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Python
uv python install "$PYTHON_VERSION"

# Bun: from the npm registry (bun.sh may not be on the allowlist)
if ! command -v bun >/dev/null || [ "$(bun --version)" != "$BUN_VERSION" ]; then
  npm install -g "bun@$BUN_VERSION" \
    || curl -fsSL https://bun.sh/install | bash -s "bun-v$BUN_VERSION"
fi

# Make the tools visible to every later shell
for rc in "$HOME/.bashrc" "$HOME/.profile"; do
  grep -q 'mosaic toolchain' "$rc" 2>/dev/null \
    || echo 'export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"  # mosaic toolchain' >> "$rc"
done

uv --version
bun --version
uv python find "$PYTHON_VERSION"
