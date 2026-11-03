#!/usr/bin/env bash
# Stop hook: Claude may not hand back a change that fails the fast gate.
# Exit code 2 sends the failure back to Claude so it keeps working.
input="$(cat)"
# Avoid loops: if this stop was already triggered by this hook, let it finish.
if printf '%s' "$input" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
# Nothing changed: nothing to check.
if git diff --quiet HEAD -- 2>/dev/null && [ -z "$(git ls-files --others --exclude-standard)" ] \
   && [ "$(git rev-list --count @{upstream}..HEAD 2>/dev/null || echo 1)" = "0" ]; then
  exit 0
fi
if ! out="$(./scripts/check-fast.sh 2>&1)"; then
  printf 'The fast gate (scripts/check-fast.sh) failed. Fix it before finishing; never weaken a test or edit spec/ or expected values to pass.\n\n%s\n' "$(printf '%s' "$out" | tail -60)" >&2
  exit 2
fi
exit 0
