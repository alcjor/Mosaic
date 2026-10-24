# Implementation decisions

Every decision taken while implementing the spec without asking first. The specs in
`docs/specs/` were left unchanged. Where a decision departs from them or fills a gap,
the entry is marked **Spec edit proposed** and says what the spec should say.

Newest last within each milestone. Each entry: what was decided, why, and what else was
considered.

Related: `docs/decisions.md` (the planning decisions D1–D15 and the spike outcomes).

---

## M0: Skeleton and spikes

**I-001 Spec bundle copied verbatim.** The uploaded bundle (`docs/`, `design/`, `prototype/`,
`.claude/skills/`, `CLAUDE.md`, `README.md`) is the repo's starting content, unchanged.

**I-002 Specs are not edited; gaps are logged here.** `CLAUDE.md` says to stop and ask on
ambiguity; the instruction for this build was to decide and log instead. So nothing in
`docs/specs/` was rewritten, and every place where the code needed more than the spec
says is an entry below.

**I-003 Spike S1 (LinkML on 3.14): passes, with two findings.**
1. A dict-valued annotation such as `mosaic.range_by: {slot: …, map: {…}}` is rejected
   by LinkML's loader (the dict is read as the fields of an `Annotation`). The valid
   LinkML form wraps it: `mosaic.range_by: {value: {slot: PCF_CATEG, map: {…}}}`. Packs use
   that form. **Spec edit proposed:** 01-core § 2.1 example should show the `value:` wrapper.
2. `gen-pydantic` models do not fill the key of a dict-inlined object
   (`sources: {srdb: {path: …}}` fails with "sources.srdb.id required"). The config loader
   therefore applies LinkML's own *SimpleDict* rules before Pydantic validation: the dict
   key fills the identifier slot, and a non-dict value fills the class's single other
   required slot. It also wraps a scalar into a list where the model expects a list
   (`sources: all`, `path: data/sum.docx`). Error paths still point at the user's YAML.

**I-004 Spike S2 (SQLite WASM with FTS5 from `file://`): passes in Chromium.**
`@sqlite.org/sqlite-wasm` 3.53.4-build2, bundled as a classic IIFE script, WASM passed as
base64 and instantiated through the `instantiateWasm` hook, store loaded with
`sqlite3_deserialize`; an FTS5 `MATCH` with `snippet()` returns in ~350 ms from a
double-clicked `index.html`, no console errors. Firefox and Edge were not available in
this environment and remain unverified.

**I-005 Spike S3 (ty on Protocols, frozen dataclasses, Pydantic): passes.** ty 0.0.91
reports assignment to a frozen field and a wrong return type, and no false positives on
a Protocol implementation or a Pydantic model. Pinned `ty==0.0.91`, `ruff==0.17.2`.

**I-006 Spike S4 (wheels on 3.14): passes on Linux.** `tree-sitter` 0.26, `tree-sitter-c`
0.24, `lxml` 6.1, `pdfplumber` 0.11 install from wheels on CPython 3.14.6; SQLite 3.53.1 with
FTS5. Windows was not available here and remains unverified.

**I-007 Mocker independence as two `forbidden` contracts.** import-linter's
`independence` contract would also forbid `mosaic_cli → mosaic_core`. Two `forbidden`
contracts express MOCK-01 exactly: the mocker imports no Mosaic package, and no Mosaic
package imports the mocker.

**I-008 `mosaic demo` runs the mocker as a subprocess.** It calls the `mosaic-mock`
console script instead of importing `mosaic_mock`, so MOCK-01 holds for the CLI too.

**I-009 Licence gate covers what ships.** `scripts/licences.py` checks the runtime
dependency closure of the five packages (`uv export --no-dev`) and fails on a package
whose only licences are GPL-family; a multi-licensed package with a permissive option
passes. The LinkML generator (`linkml`, dev group only, used to regenerate the Pydantic
models) pulls `rfc3987` (GPLv3+) through `jsonschema[format]`; it is a build-time tool,
never shipped, so it is outside the gate. Alternative: drop `linkml` and hand-write the
models, which would break CORE-10.

**I-010 CI action versions.** Kept the majors from engineering.md § 8 (`checkout@v4`,
`setup-uv@v6`, `setup-node@v4`, `upload-artifact@v4`); newer majors could not be verified
from this environment. Bump them once checked.

**I-011 Coverage gate runs the tests once.** `scripts/check.py` (full and `--python`)
runs every non-e2e test under branch coverage through `scripts/coverage_gate.py`, which
enforces ≥ 90 % for `mosaic_core` and ≥ 80 % for the other packages. `--fast` runs the
unit tests without coverage.

**I-012 Traceability counts viewer tests by title.** `scripts/trace.py` reads Python
`@pytest.mark.req(...)` markers and requirement IDs in the titles of Vitest and Playwright
tests (`*.test.ts`, `*.spec.ts`). It fails on gaps; `--warn` reports only.

---

## Dependencies

Every dependency added, with its licence (D14, engineering.md § 9). All are on the planned
list in engineering.md § 9 unless marked *new*.

| Package | Used by | Licence | Replaces / why |
|---|---|---|---|
| linkml-runtime | core | CC0-1.0 | Reads the system schemas (SchemaView) |
| pydantic | core | MIT | Generated config models (CORE-10/11) |
| pyyaml | core, mock | MIT | *new*: YAML config and pack files (already a transitive dependency of linkml-runtime) |
| lxml | extractors | BSD-3-Clause | HTML parsing |
| mammoth | extractors | BSD-2-Clause | `.docx` → HTML, then the `html` extractor (CORE-31) |
| pdfplumber | extractors | MIT | PDF words, font sizes, ruled tables |
| tree-sitter, tree-sitter-c | extractors | MIT | C parsing |
| fastapi, uvicorn | server | MIT, BSD-3-Clause | Live server |
| watchfiles | server | MIT | *new*: `mosaic serve --watch` (VIEW-72) |
| jinja2, python-docx, reportlab | mock | BSD, MIT, BSD | Prose templates, `.docx`, PDF |
| anthropic (extra `llm`) | mock | MIT | *new*: optional `--llm anthropic` provider (MOCK-21/22) |
| linkml (dev) | gen | CC0-1.0 | `gen-pydantic` (CORE-10); see I-009 |
| pypdf (dev) | mock tests | BSD-3-Clause | PDF text check (MOCK-41) |
| httpx (dev) | server tests | BSD-3-Clause | *new*: FastAPI test client |
| jsonschema (dev) | mock tests | MIT | *new*: validates `ground_truth.json` against its schema |
