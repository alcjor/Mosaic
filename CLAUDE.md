# CLAUDE.md

Mosaic — Connected manual. Read-only exploration of data joined from several sources,
with text connections and tailored views. Generic core; spacecraft is the first system
pack.

## Where things are

- Specs (source of truth): `docs/specs/00-overview.md` … `04-mocker.md`
- How we work: `docs/engineering.md`; decisions: `docs/decisions.md`
- Python packages: `packages/mosaic-{core,extractors,server,cli,mock}`
- Named SQL shared with the viewer: `queries/`
- System packs: `packs/spacecraft/`, `packs/_toy/`
- Viewer: `viewer/` (Svelte 5 + Vite + TypeScript)
- Design system (read-only copy) and how it applies to the viewer: `design/mosaic/`, `design/viewer-guidelines.md`; agreed look: `prototype/index.html`

## Commands

```
uv sync --all-packages                 # set up
uv run scripts/check.py                # every gate; run before saying "done"
uv run scripts/check.py --fast         # lint, types, unit tests
uv run pytest packages/mosaic-core     # one package
uv run mosaic-mock generate --profile spacecraft --out examples/demosat-1
uv run mosaic build examples/demosat-1/mosaic.yaml
uv run mosaic demo
cd viewer && npm run dev | npm test | npm run check
```

## Project rules

- Work from the spec. Cite requirement IDs (`CORE-41`) in plans, tests and commits.
  If the spec is ambiguous or seems wrong, stop and ask; propose the spec edit.
- Tests first: write the requirement's test, see it fail, then implement. Tag tests with
  `@pytest.mark.req("<ID>")`.
- Respect package boundaries (`docs/engineering.md` § 2). `mosaic_mock` never imports
  another Mosaic package.
- No domain words in `mosaic_core`, `mosaic_extractors` or `viewer/src` (CORE-01,
  VIEW-03). Spacecraft knowledge goes in `packs/spacecraft/` as config.
- Any UI work follows the `mosaic-design` skill: tokens only, colours keep their meaning,
  logos unchanged, fonts bundled. Never edit `design/mosaic/`; if it lacks something, ask.
- Never execute FOPs or C code; parse only.
- The store schema and `queries/` are a contract: change them only with a spec update and
  a `store_version` bump.
- No network at build, serve or export time. No CDN or remote fonts in the viewer.
- New dependency → permissive licence and a line in `docs/decisions.md`.
- Python ≥ 3.14, typed; ruff and ty clean. `# ty: ignore[...]` needs a reason.
- Generated files (Pydantic models from LinkML, query types, `examples/demosat-1`) are
  regenerated, never hand-edited.

---

## Coding guidelines (Karpathy)

Vendored from [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills)
(MIT); also available as the `karpathy-guidelines` skill in `.claude/skills/`.

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

Project note: configurability *is* requested here, but only where the specs ask for it.
The spec is the boundary.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
