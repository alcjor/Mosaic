#!/usr/bin/env bash
# PreToolUse hook: block `git push` unless the fast gate passes locally,
# so CI minutes are never spent finding failures.
input="$(cat)"
if ! printf '%s' "$input" | grep -qE '"command"[[:space:]]*:[[:space:]]*"[^"]*git[^"]*[[:space:]]push'; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
. .claude/hooks/gate-cache.sh
# This exact tree already passed (an earlier push, a sheet publish, a retry): nothing to check.
gate_passed_already && exit 0
if ! out="$(gate_run)"; then
  printf 'Push blocked: scripts/check-fast.sh failed locally. Fix it, rerun, then push.\n\n%s\n' "$(printf '%s' "$out" | tail -60)" >&2
  exit 2
fi
exit 0
