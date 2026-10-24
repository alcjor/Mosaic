# Decision log

Newest last. Each entry: decision, why, alternatives considered.

## 2026-10-24 — Planning session

**D1 Generic core, spacecraft as the first pack.** The goal is a tool for any system:
generic data with text connections and tailored views. Alternatives: a spacecraft-specific
tool (faster to start, but every later domain would fork it).

**D2 LinkML for schemas, YAML for config.** A formal schema replaces relview's own YAML
DSL; LinkML generates Pydantic, JSON Schema, SQL and OWL, which fits the later ontology
and SysML v2 work. Alternatives: Pydantic only (simpler, informal), RDF/OWL (heavier for
everyday code). Risk: Python 3.14 support, spike S1.

**D3 uv workspace, several packages, Python ≥ 3.14, pytest.** Package boundaries are
enforced by dependencies and import-linter. Alternative: one package with subpackages.

**D4 Exact matching in v1 behind a `Matcher` interface.** Deterministic and auditable now;
fuzzy and AI-assisted matchers plug in later without schema changes. Alternatives: exact +
fuzzy, or exact + fuzzy + AI suggestions in v1.

**D5 SQLite store with FTS5.** One portable file, readable from notebooks, servable, and
shippable in a static export via WASM. Alternatives: SQLite with JSON export, DuckDB.

**D6 Svelte + Vite viewer; one codebase for live and static.** Small static bundles; one
data layer with HTTP and WASM backends. Alternatives: Jinja + HTMX pre-rendered, React,
vanilla TS.

**D7 Reflowed HTML for documents, code and scripts.** Uniform linking and search.
Alternatives: PDF pages with overlays, both.

**D8 Views in YAML; a view defines its export scope; one shipped view (ops).** Anyone can
define a view; customer exports are views. Alternatives: views plus custom components, an
in-app view editor (later, saving to the same YAML).

**D9 Ops view: reader + detail panel.** Item-centric, suits following a FOP step by step.
SRDB tables open in the main pane. Alternatives: search first, reader + synced table.

**D10 Fully offline.** Ops networks and customer data packs. No CDN, no remote fonts.

**D11 Telemetry: interface only.** Schema slot, protocol, config key; no UI. Integration
with the mission time-series platform comes later.

**D12 Mocker: generic engine + spacecraft profile; small default; defects with ground
truth; templates with optional LLM.** Alternatives: spacecraft-only mocker; clean data
only; LLM prose by default.

**D13 Quality tooling: ruff + ty, GitHub Actions, Karpathy guidelines vendored.** ty is
beta; pinned, and spike S3 checks it copes. Alternatives: pyright strict, mypy strict;
GitLab CI; plugin install of the guidelines.

**D14 Private repo for now, permissive dependencies only.** Keeps the option to open it.

## 2026-10-25

**D15 The viewer follows the MOSAIC design system.** Logo ("the last shard"), tokens,
type and colour meanings come from the existing MOSAIC design system; the first
prototype used an invented mark by mistake. Corporate blues remain placeholders (Q6).

## Spikes (M0)

| Spike | Question | Outcome |
|---|---|---|
| S1 | LinkML generation and validation on Python 3.14 | Passes (linkml 1.12.1, pydantic 2.14). Dict-valued annotations need LinkML's `value:` wrapper; keyed dicts need the loader's SimpleDict normalisation (I-003) |
| S2 | `@sqlite.org/sqlite-wasm` with FTS5 from `file://` | Passes in Chromium (3.53.4-build2, classic IIFE bundle, WASM from base64 via `instantiateWasm`, ~350 ms). Firefox/Edge unverified (I-004) |
| S3 | ty on Protocols, dataclasses, Pydantic | Passes with ty 0.0.91 (I-005) |
| S4 | Wheels for tree-sitter, lxml, pdfplumber on 3.14 (Linux, Windows); FTS5 in uv's Python on Windows | Linux passes (3.14.6, SQLite 3.53.1, all wheels). Windows unverified (I-006) |

## Implementation

Decisions taken during the first implementation are logged one by one in
[`implementation-decisions.md`](implementation-decisions.md) (I-001 onwards), including the
spec edits they propose. New dependencies are listed there too (§ "Dependencies").
