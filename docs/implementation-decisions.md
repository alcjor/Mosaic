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

## M1: Mocker

**I-013 Placements are read off the final models, not recorded while rendering.**
Renderers build models (lines of code, document trees, SRDB rows) whose references are
typed `Ref` pieces carrying item, role and match. Defects mutate those models, then the
ground truth is read from them and the files are serialized from them. This keeps the
ground truth and the files in step by construction (MOCK-12, MOCK-25). The spec's
`Renderer → Placements` contract still holds, one step later.

**I-014 Ground-truth additions.** Besides the fields of 04 § 3, `ground_truth.json` has
`edges` (the world's relations, e.g. `PLF_NAME`, `handles`), `files` (path + sha256 of
every written file), `defect_set`, `scale` and `llm`. Xref scopes use a small vocabulary:
`file`, `step=<n>`, `section=<number>`, `function=<name>`. A JSON Schema ships with the
mocker (`ground_truth.schema.json`). **Spec edit proposed:** list these in 04 § 3.

**I-015 Fixed anchors reproduce the spec's examples.** The PWR subsystem fixes
`PWRT0012`, `PWRT0020`, `PWRT0031`, `PWRT0045`, `PWRC0101`, `PWRC0112`, `PWRC0123`,
`PWRP0001`, `PWRP0010`, SPID 1001, so the small mission's FOP-PWR-001 is byte-identical
to the example in 04 § 5.2 (a test checks it). The prototype's `PWRT0013`, `PWRC0102` and
`PWRC0110` were dropped: they are one edit away from `PWRT0012`/`PWRC0101`, which the
distance rule forbids. All other IDs are random 4-digit numbers, registered before use.

**I-016 Distance rule is Hamming ≥ 2 across every ID of equal length**, all types
together (so `PWRT0101` and `PWRC0101` cannot both exist). Mnemonics and packet names
are globally unique but not distance-guarded.

**I-017 What counts as linkable follows the pack (02 § 3).** IDs of PCF/CCF/CPC,
mnemonics of PCF/CCF and packet names (`TPCF_NAME`) are `exact`; long descriptions
(`PCF_LDESCR`, `CCF_DESCR2`, `CPC_DESCR2`) and argument mnemonics (`CPC_DESCR`, not a
surface form) are written as `fuzzy_only`, the benchmark for a future matcher.

**I-018 SRDB column specs were written from memory of the public SCOS-2000 MIB ICD.**
Names, order and mandatory flags of 18 tables (VDF, PCF, CAF, CAP, TXF, TXP, MCF, LGF,
CUR, PID, PIC, TPCF, PLF, OCF, OCP, CCF, CPC, CDF). They must be checked against the
issue the project uses (Q1; 02 § 3 says "to be checked in M2"). The mocker keeps its own
copy (MOCK-01); a contract test compares it with the pack's.

**I-019 SRDB content.** Every analogue parameter gets a calibration: linear CAF with two
CAP points, polynomial MCF for temperatures, logarithmic LGF for a few signal levels.
Status parameters share one TXF per state set per subsystem. ~30 % of generated analogue
parameters (and every curated one with limits) get an OCF with a soft and a hard OCP.
One CUR pair switches the solar array current to an alternative CAF in boost mode.
`PCF_PID` is `0x<subsystem><number>`; custom column `PCF_LDESCR` follows all 24 standard
PCF columns.

**I-020 Packets.** One HK packet per subsystem, PUS (3,25), SPIDs from 1001 (larger
sizes split a subsystem over several, `PWR_HK1`, `PWR_HK2`, …), plus `EVT_INFO` (5,1) and
`EVT_ALARM` (5,4) carrying two OBC parameters, SPIDs 2001–2002. Byte offsets start at 16.

**I-021 C code shape.** `include/demosat_ids.h` (`#define PARAM_<id>`),
`include/demosat_tc_ids.h` (`typedef enum { TC_<id> = … }`), and per subsystem
`src/<ss>_app.h` and `src/<ss>_app.c` with one static handler per TC, a
`<ss>_tc_dispatch()` with `case TC_<id>:` labels, `<ss>_hk_fill()` using `PARAM_` IDs and
`<ss>_init()`. Medium and large sizes add `src/<ss>_drv_<n>.c` driver files to reach the
file count. Every function definition becomes a `Function` item keyed
`<path under scsw/>::<name>` (e.g. `src/pwr_app.c::pwr_tc_dispatch`) with `name`, `file`,
`line`; the dispatcher has `handles` edges to its TCs.

**I-022 `documented_in` uses both rule shapes.** The generated `mosaic.yaml` maps each
`src/<ss>_app.c` to its manual chapter (`heading_regex: '^4 Power application'`); the
headers fall back to "≥ 2 shared entities" with the `n.2`/`n.3` sections. The explicit
map wins for a file it matches; the fallback applies to files no map entry matches.

**I-023 Documents.** Section numbers are part of the heading text (`4.2 Telecommands`;
appendix `A Acronyms`). The manual is one model written as `.docx` (python-docx, header
rows marked `tblHeader`, Caption style before each table) and PDF (ReportLab, Helvetica
base-14 fonts, ruled tables with repeated headers, a footer line in the bottom margin,
a bookmark per heading, ASCII `-` bullets because Helvetica's bullet extracts as
`(cid:127)`). The ICD is plain generated HTML that includes a `<script>` and an `onclick`
handler, so the HTML extractor's stripping (CORE-32) is exercised on real input.

**I-024 Sizes.** The counts match 04 § 5.1 (small: 6 subsystems, 80 PCF, 30 CCF,
8 packets, 6 FOPs, 14 C files). The manuals are shorter than the table says: 9 pages
(small, ~25 expected), ~57 (medium, ~150) and ~270 (large, ~500), because each item gets
one table row and little prose. Revisit if CORE-95 needs a longer manual. Curated
vocabulary is a floor: `--scale` below 1 never drops curated items.

**I-025 Defect sets.** `default` = one of each v1-detectable kind plus two `future`
kinds; `all` = two of every kind; a YAML file lists `{kind, count}`. Per-kind *rates*
(04 § 7 "at configurable rates") are not implemented; counts cover the need.

**I-026 Optional LLM rewrite.** `--llm anthropic` uses the official SDK (extra
`mosaic-mock[llm]`), model `claude-opus-5-5`, effort `low`, with the server-side refusal
fallback (`fallbacks: "default"`); a refusal or a lost token keeps the template text.
Only prose paragraphs are rewritten (never tables, headings, code). Cached by prompt hash
under `mock-cache/<profile>/`. Not run against the live API here (no key); tested with
fake providers.

**I-027 Output folder safety.** `generate --out` replaces a folder only if it is a
previous mocker output (it contains `ground_truth.json`); otherwise it refuses.

**I-028 Toy profile.** A bicycle workshop: `data/parts.csv` and `data/suppliers.csv`
(comma-separated, with header), `docs/catalogue.html` (sections per supplier, a
*Part · Name · Stock* table) and `docs/assembly.html` (bullets naming parts). Part names
are multi-word surface forms ("brake lever"), IDs follow `P-\d{3}`. Xref type
`uses_part_from` (assembly section → catalogue section).

**I-029 Determinism tests.** Besides two-runs-equal and golden hashes, MOCK-31 is tested
by generating under three `PYTHONHASHSEED` values, which catches set-order leaks that a
code scan cannot.

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
| anthropic (extra `llm`) | mock | Apache-2.0 | *new*: optional `--llm anthropic` provider (MOCK-21/22) |
| linkml (dev) | gen | CC0-1.0 | `gen-pydantic` (CORE-10); see I-009 |
| pypdf (dev) | mock tests | BSD-3-Clause | PDF text check (MOCK-41) |
| httpx (dev) | server tests | BSD-3-Clause | *new*: FastAPI test client |
| jsonschema (dev) | mock tests | MIT | *new*: validates `ground_truth.json` against its schema |
