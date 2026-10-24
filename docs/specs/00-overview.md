# Mosaic — Connected manual: overview

Status: draft 0.1 · 2026-10-25

This repository builds the **Connected manual**, the first phase of Mosaic. It is built
as Mosaic's core from day one, so later phases (telemetry, fuzzy/AI matching, SysML v2,
cross-mission comparison) plug in without changing the core contracts.

## What it does

Mosaic reads data that already exists, declares how the pieces relate, and lets people
navigate it. It never edits the sources.

```
sources (files)  ──extract──▶  entities + text segments  ──link──▶  store (SQLite)  ──▶  viewer
SRDB, ICD, manual,              typed records, sections,             one portable file     live server
C code, FOPs                    tables, functions, steps                                   or static export
```

The core is **domain-neutral**: "generic data with text connections, with a tailored view".
Everything spacecraft-specific lives in a **system pack** (`packs/spacecraft/`), which is
configuration and templates, not code.

## Documents in this folder

| File | Contents |
|---|---|
| `00-overview.md` | This file: scope, glossary, decisions, open questions |
| `01-core.md` | Domain-neutral core: schema, config, pipeline, extractors, matching, store, extension points |
| `02-spacecraft-pack.md` | The spacecraft tailoring: SRDB, ICD, SW user manual, C code, FOPs, link rules, the ops view |
| `03-viewer.md` | UI: building blocks, view configs, the default ops view, live and static modes |
| `04-mocker.md` | Generic mock-data engine and the spacecraft profile, with defects and ground truth |
| `../engineering.md` | Repo structure, quality practices, CI, milestones |

Every requirement has an ID (`CORE-12`, `PACK-03`, `VIEW-10`, `MOCK-21`). Tests reference
these IDs (see `engineering.md` § Traceability).

## Glossary

| Term | Meaning |
|---|---|
| **System pack** | Tailoring for one *kind* of system: LinkML system schema, source definitions, link rules, views, templates. Reusable across missions. |
| **Project** | One concrete system (e.g. one mission): a `mosaic.yaml` that selects a pack and points at the actual files. |
| **Source** | One input declared in the project (a file or a set of files) bound to an extractor. |
| **Record source** | A source whose content becomes entities (e.g. SRDB tables). |
| **Text source** | A source whose content becomes segments (documents, HTML pages, code, scripts). A text source may also emit entities (e.g. C functions). |
| **Entity** | A typed record with a key, attributes and a provenance location. |
| **Relation** | A typed edge between two entities (from the schema, or promoted from a mention by a rule). |
| **Segment** | An addressable piece of text in a tree: document › section › paragraph, table › row › cell, file › function, script › step. |
| **Mention** | A span inside a segment that refers to an entity, with a **role** (`mentions`, `describes`, `sends`, `reads`, `defines_id`, `handles`, …). Unresolved mentions have no entity. |
| **Cross-reference** | A segment↔segment link derived by a rule (e.g. FOP step ↔ manual section describing the same TC). |
| **Diagnostic** | A build finding: unresolved reference, format deviation, duplicate key, broken relation. |
| **View** | A YAML config arranging viewer building blocks, labels, columns and panel groups, plus the scope of a static export. |
| **Store** | The build output: one SQLite file, the contract between Python, the viewer and future Mosaic tools. |
| **Export** | A static, fully offline folder produced from a view. |

## Scope of v1

In:

- Sources: SCOS-2000 SRDB/MIB ASCII tables, SW ICD as an HTML page with tables, SW user
  manual as `.docx` and PDF, on-board SW C code, FOPs as Python scripts.
- Links (configurable): mention → entity; entity → all mentions (backlinks);
  FOP ↔ SW user manual / ICD / code cross-references; whole code file ↔ manual sections.
- Exact matching of IDs and mnemonics, with a matcher plug-in slot for fuzzy/AI later.
- Diagnostics needed to catch the mocker's defects (unresolved references, format
  deviations, duplicate keys, broken relations).
- Full-text search across all sources, live and offline.
- Viewer: navigator, reader, table browser, detail panel, search; user-defined views in
  YAML; one shipped default view for operations engineers.
- Delivery: live local server and static offline export from the same viewer code.
  A view defines what an export contains.
- Telemetry hook: schema slot and extension point only, nothing in the UI.
- Mocker: generic engine plus a spacecraft profile, small default size, configurable
  defects with ground truth, templates with optional LLM prose.

Out of v1 (designed for, not built):

- Fuzzy and AI-assisted matching (slot exists: `CORE-40`).
- Full consistency report (unit or description mismatches across sources).
- Relationship graph view.
- Telemetry display (hook exists: `CORE-60`).
- SysML v2 export, cross-mission comparison, Jupyter helpers beyond the SQLite store.
- Editing anything. Mosaic is read-only.

## What you need to run it

| Who | Needs |
|---|---|
| Developers | Git, uv (it installs Python 3.14), Node LTS with npm (only to build the viewer), optionally Claude Code |
| Users of the live viewer | uv and the Mosaic packages, which ship the built viewer; a current browser. No database server and no Node: SQLite with FTS5 is part of Python |
| Recipients of an export (MOSAIC Tessera) | A current browser only: the export opens from a folder or a single HTML file, offline, with no server and nothing to install |

FTS5 in the static export comes from SQLite itself, compiled to WebAssembly and embedded in
the export (VIEW-50); it does not need a server. Spike S2 proves this before M1.

## Decisions taken

From the planning session (2026-10-24). Details and rationale in `../decisions.md`.

| # | Decision |
|---|---|
| D1 | Generic, configurable core; spacecraft is the first system pack |
| D2 | Formal schema in LinkML; YAML config validated against it |
| D3 | uv workspace with several packages; Python ≥ 3.14; pytest |
| D4 | Exact matching in v1 behind a matcher interface |
| D5 | Store is one SQLite file with FTS5 |
| D6 | Viewer in Svelte + Vite; one codebase for live server and static export |
| D7 | Documents, code and scripts shown as reflowed HTML |
| D8 | Views defined in YAML; a view defines its export scope; one default view (ops) |
| D9 | Default ops view: reader + detail panel |
| D10 | Fully offline: no CDN, no external fonts |
| D11 | Telemetry: interface only |
| D12 | Mocker: generic engine + spacecraft profile; small default; defects with ground truth; templates, LLM optional |
| D13 | Quality: ruff + ty, GitHub Actions, Karpathy guidelines vendored in `.claude/skills` + `CLAUDE.md` |
| D14 | Repo private for now; dependencies kept permissive (no AGPL/GPL) so it can be opened later |
| D15 | The viewer follows the MOSAIC design system (logo, tokens, colour meanings) |

## Open questions

Each has a proposed default the implementation uses until answered.

| # | Question | Proposed default |
|---|---|---|
| Q1 | Which SCOS-2000 Import ICD issue and which tables does your SRDB use? Which custom columns? | Issue configurable; table set in `02` § SRDB; custom columns declared per project |
| Q2 | When a manual exists as both `.docx` and PDF, which is authoritative? | `.docx` for content; PDF only when no `.docx` |
| Q3 | Should ICD HTML rows also become entities, or stay text? | Text with table-aware roles |
| Q4 | What do your real Python FOPs look like (TC/TM function names, how steps are marked)? | Configurable; mock uses `send_tc`, `verify_tm`, `@step` |
| Q5 | Conventions in your C code for IDs (`#define` / `enum` naming) and TC handlers? | Configurable patterns; mock conventions in `04` |
| Q6 | Corporate blue hex codes and typeface, to replace the MOSAIC design system placeholders? | MOSAIC design system tokens; IBM Plex bundled |
| Q7 | Do users run Windows? (CI matrix, path handling) | CI on Ubuntu and Windows |
| Q8 | Is case-insensitive matching ever wanted? | Case-sensitive, configurable per entity type |
| Q9 | Name of the fictional demo mission | `DEMOSAT-1` |
