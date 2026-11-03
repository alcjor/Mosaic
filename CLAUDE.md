# Mosaic — instructions for agents

Mosaic builds small, sealed knowledge graphs (SQLite files) that travel with small
AI models. Python builds tesserae and mosaics; one TypeScript kit reads them, in
the browser for the viewer and later in Node for agents.

**The spec is the product.** Read before you build:
- `docs/spec-0.1.md` — the normative contract (Part 5). Cite section numbers in PRs.
- `spec/` — the five normative files. Where they and the text disagree, the file
  wins for structure, the text for meaning, and the disagreement is a defect: open an issue.
- `docs/adr/` — why things are the way they are. `docs/design.md` — everything, in reading order.

## Principles (a design that breaks one is wrong, however convenient)

1. Agents first, people too. 2. Small by design. 3. Build any way; fix the result, not the method.
4. Every fact says where it came from (evidence on every node and edge).
5. Building mosaics is deterministic: same pieces + pattern → same knowledge hash.
6. Sealed and shareable: immutable, versioned, named by hash.
7. Copy what fits, reference what doesn't. 8. Never write to a source.
9. **Domain-neutral**: no domain words in format, builder or kit (a test enforces it;
   tessera builders under `mosaic_build/tessera/` are exempt).
10. Offline, embedded, open: one file, a small library, no server. Apache-2.0.

## Boundaries

- `packages/mosaic-format` (schema, hashes, checker) never imports `mosaic_build`
  (import-linter enforces it).
- The kit (`kit/`) never imports Python code or the viewer. Python and TypeScript
  meet only at the mosaic file and the cases in `conformance/`.
- The mosaic builder uses no AI and no network.

## Commands

```
uv sync && npm ci               # install
./scripts/check-fast.sh         # the gate: ruff, ty, import-linter, pytest, tsc/svelte-check, vitest
uv run pytest -m slow           # budgets and large fixtures
uv run mosaic --help            # CLI
npm run build                   # kit + viewer
```

A Stop hook runs `scripts/check-fast.sh` before you finish; a failure sends you back.

## Rules for every change

- **One issue, one PR.** Branch `issue-<n>-<slug>`, PR body says `Closes #<n>` and
  shows how each "Done when" item is met (test names, commands, output).
- **Tests first for behaviour.** Every change adds or extends tests. Test against
  the spec's words, not against your implementation.
- **Never** edit `spec/`, `docs/`, `conformance/**/expected*`,
  `conformance/fixtures/manifest.json`, `.github/`, `.claude/`, this file or
  `scripts/check-fast.sh` to make something pass. Never skip, xfail or loosen a
  test to go green. These paths are CODEOWNERS-protected; PRs touching them wait for the maintainer.
- **Ambiguity stops you.** If the spec is unclear, silent or contradictory, do not
  decide: comment on the issue with the question and the options you see, add the
  label `needs-decision`, remove `in-progress`, and stop.
- Determinism matters on Linux, macOS and Windows: no dependence on dict/set order,
  locale, line endings (`.gitattributes` forces LF), path separators or file-name case.
  Text compares by UTF-8 bytes unless the spec says otherwise.
- Keep dependencies few; add one only when it clearly earns its place, and say why in the PR.
- Fixture sources are never committed; they are downloaded and pinned by hash
  (`scripts/fetch_fixtures.py`). All example data is invented or openly licensed.

## Work queue (GitHub issues)

- Labels: `m0`…`m8` (milestone), `ready` (unblocked), `in-progress`, `blocked`,
  `needs-decision` (waiting for the maintainer), `agent` (fit for autonomous work).
- Take the oldest open issue labelled `ready` and not `in-progress`. Label it
  `in-progress` first. When your PR merges, re-label issues it unblocks (their
  "Blocked by" list is all closed) from `blocked` to `ready`.
- A milestone is done when its "Done when" in `docs/design.md` (Implementation
  plan → Milestones) passes. Don't start the next milestone's issues early.

## Style

Python 3.14, typed, ruff-formatted, line length 100. TypeScript strict. Small
modules, plain names from the glossary (tessera, mosaic, piece, pattern, target,
evidence, mention, kit). Errors name what failed and where (piece, locator).
