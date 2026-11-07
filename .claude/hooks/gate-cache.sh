#!/usr/bin/env bash
# Sourced by the pre-push and Stop hooks: run the fast gate once per exact working tree.
# The key is a git tree hash of every tracked and untracked, non-ignored file as it is on disk,
# plus the uv and Bun versions. Only a pass is recorded, in .git (never in the tree), so a
# failing tree always runs the gate again. MOSAIC_GATE_NOCACHE=1 forces a full run.

# The temporary index starts empty, so git reads and hashes every file. A copy of the real
# index would let git trust its recorded sizes and timestamps, and an edit that keeps them
# would look unchanged (a changed tree once skipped the gate this way).
gate_tree_id() {
  local dir idx id
  dir="$(mktemp -d)" || return 1
  idx="$dir/index"
  id="$(GIT_INDEX_FILE="$idx" git add -A . >/dev/null 2>&1 && GIT_INDEX_FILE="$idx" git write-tree)"
  rm -rf "$dir"
  [ -n "$id" ] && printf '%s\n' "$id"
}

gate_key() {
  local tree
  tree="$(gate_tree_id)" || return 1
  printf '%s uv=%s bun=%s\n' "$tree" "$(uv --version 2>/dev/null)" "$(bun --version 2>/dev/null)"
}

gate_stamp() { git rev-parse --git-path mosaic-gate-pass; }

# True when this exact tree already passed the gate.
gate_passed_already() {
  [ -z "${MOSAIC_GATE_NOCACHE:-}" ] || return 1
  local key
  key="$(gate_key)" || return 1
  [ "$(cat "$(gate_stamp)" 2>/dev/null)" = "$key" ]
}

# Runs the gate; on a pass, records the tree it passed on. Prints the gate's output.
gate_run() {
  local key
  key="$(gate_key)"
  ./scripts/check-fast.sh 2>&1 || return 1
  [ -n "$key" ] && printf '%s\n' "$key" > "$(gate_stamp)"
  return 0
}
