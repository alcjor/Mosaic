# 03 — Viewer

Status: draft 0.1 · Folder: `viewer/` (Svelte 5 + Vite + TypeScript) · Server: `mosaic-server`

The viewer knows building blocks and the store contract. Everything domain-specific
(labels, columns, panel groups, navigator) comes from a view config.

## 1. Principles

- **VIEW-01** One codebase, two modes: **live** (served by `mosaic serve`, reads through
  the HTTP API) and **static** (exported folder, reads an embedded SQLite through WASM).
  Mode is chosen at boot from `window.__MOSAIC__`, written by the server or the exporter.
- **VIEW-02** Fully offline: no CDN, no remote fonts, no analytics, no network calls
  except to its own server in live mode.
- **VIEW-03** Nothing in `viewer/src` mentions a pack type (`PCF`, `CCF`, …). A lint test
  enforces it, like CORE-01.
- **VIEW-04** Read-only. No editing, no writes back to the store.

## 2. Building blocks

| Block | Does |
|---|---|
| App shell | Header with project name, view switcher, search box, diagnostics badge; hosts the panes |
| Navigator | Groups of sources and tables from the view config; source trees (document › section, file › function, FOP › step) |
| Reader | Renders any text source as reflowed HTML: document tree, HTML tables, C code, Python scripts, all with mention links |
| Table browser | One entity type as a table: sort, filter per column, column chooser, virtualised rows, row → detail |
| Detail panel | The selected entity: title, subtitle, then groups from the view config (attributes, relations, mentions, cross-references) |
| Entity page | The same entity full width in the main pane: every attribute, relations as tables (e.g. a packet's layout, a TC's arguments), every mention group in full |
| Search | Full-text over segments and entities (FTS5), results grouped by source and entity type |
| Diagnostics list | Filterable list; each item opens its location |
| History | Back/forward over every hop, plus a breadcrumb of the last hops |

A relationship graph is a future block (out of v1).

## 3. Interaction model (ops view: reader + detail panel)

- **VIEW-10** Clicking a mention in the reader opens its entity in the detail panel and
  marks the span as current. The reader does not move.
- **VIEW-11** Clicking an item in the detail panel:
  - a related entity → the panel shows that entity (a hop, recorded in history);
  - a mention or cross-reference → the reader opens that segment, scrolls to it and
    highlights the span.
- **VIEW-12** The main pane shows a text source, a table or an entity page. Exploring the
  SRDB means opening its tables from the navigator, hopping item to item in the panel, or
  opening an item as a page.
- **VIEW-18** *Open page* in the detail panel shows that entity as an entity page in the
  main pane; the panel hides while the page shows. On the page, related entities open
  their own page (a hop, recorded in history); mentions and cross-references open the
  source at that spot, with the entity back in the panel.
- **VIEW-13** Scope segments (FOP steps, manual sections, C functions) show their
  cross-references as chips under their heading, e.g. *Described in 4.2 · Defined in
  ICD 4.1 · Handled by `pwr_tc_dispatch()`*.
- **VIEW-14** Unresolved mentions are shown with a dashed underline in the warning colour;
  hovering or focusing shows the diagnostic and its suggestions. They are not links.
- **VIEW-15** Hover or focus on a mention shows a preview (title, subtitle, type label)
  after 300 ms on pointer devices; on touch, the first tap opens the panel directly.
- **VIEW-16** Keyboard: `/` focuses search, `Alt+←` / `Alt+→` history, `Esc` closes the
  panel, every link reachable with `Tab`.
- **VIEW-17** Narrow screens (< 900 px): the panel becomes a bottom sheet over the reader.

## 4. Routing

Hash routing, so deep links work from `file://` and from the server alike.

| Route | Shows |
|---|---|
| `#/s/<segment-id>?m=<mention-id>` | Segment in the reader, optionally highlighting a mention |
| `#/t/<Type>?q=&sort=&cols=` | Table browser |
| `#/e/<Type>/<key>` | Entity page |
| `#/search?q=` | Search results |
| `#/diagnostics?code=&severity=` | Diagnostics list |
| any route `&e=<Type>/<key>` | Detail panel open on that entity |

- **VIEW-20** Every state worth sharing has a route; reloading a route restores it.

## 5. View config

Validated against the core schema (LinkML class `View`).

| Field | Meaning |
|---|---|
| `id`, `title`, `audience` | Identity, shown in the view switcher |
| `layout` | `{navigator: bool, main: reader \| table, side: detail \| none}` |
| `landing` | `{source: <id>}`, `{table: <Type>}` or `{search: true}` |
| `navigator` | Ordered groups: `{title, sources: [...]}` or `{title, tables: [...]}` |
| `types.<Type>` | `label`, `title` slot, `subtitle` slot, default table `columns`, optional `column_labels` |
| `detail.<Type>` | Ordered groups (below); a type with no entry gets attributes, all relations, all mentions |
| `export` | `{sources: all \| [...], types: all \| [...], diagnostics: bool}` |
| `theme` | `{preset: corporate \| neutral, overrides: {token: value}}` |

Detail groups:

| `show` | Options |
|---|---|
| `attributes` | `only: [...]` or `except: [...]` |
| `relations` | `type` + `direction: in \| out`, or a `path` |
| `mentions` | `roles`, `sources`, `group_by: source \| scope` |
| `xrefs` | `types` |
| `external` | Reserved for the telemetry hook; ignored in v1 |

The panel and the entity page use the same groups. On the page, a `relations` group is
drawn as a table: one row per related entity with the target type's default columns, plus
the attributes of the joining row when the path goes through one (e.g. `PLF` byte and bit
offsets for a packet's layout).

**Path syntax** walks relations from the current entity: `slot->` follows an outgoing
relation; `Class.slot<-` follows an incoming one from entities of `Class`; ` / ` chains
steps. Example: `CDF.CDF_CNAME<- / CDF_PNAME->` = elements of this TC, then their argument.

- **VIEW-30** An invalid view fails `mosaic check` with the YAML path of the error.
- **VIEW-31** Views are files in the pack (`views/*.yaml`) or the project (`views:` in
  `mosaic.yaml`); a project view with the same id replaces the pack's.
- **VIEW-32** Export scope: `mosaic export --view X` writes a store containing only X's
  sources and types. `types` decides which entities travel (with their pages, panel and
  search) even when their source's tables are not in the navigator, so an export can link
  ICD mentions to parameter pages without exposing the SRDB tables themselves. Mentions whose entity is out of scope become plain text;
  cross-references to out-of-scope segments are dropped; diagnostics only if
  `export.diagnostics` is true. Example customer view, not shipped:
  ```yaml
  id: customer
  title: Data pack
  extends: ops                         # inherit everything, override below
  navigator:
    - {title: Procedures, sources: [fops]}
    - {title: SW user manual, sources: [sum]}
    - {title: SRDB, tables: [PCF, CCF, CPC]}
  export: {sources: [fops, sum, srdb], types: [PCF, CCF, CPC, CDF, PLF, PID], diagnostics: false}
  ```
- **VIEW-33** `extends` merges one level deep (top-level keys replace; `types` and
  `detail` merge per type).

## 6. Data layer

```ts
interface Backend {
  meta(): Promise<StoreMeta>;
  query<N extends QueryName>(name: N, params: QueryParams[N]): Promise<QueryResult[N]>;
}
```

- **VIEW-40** `HttpBackend` calls `GET /api/q/<name>?…`; `WasmBackend` runs the same SQL
  from `queries/*.sql` (imported at build time as text) on SQLite WASM. Query types are
  generated from the query headers (CORE-80).
- **VIEW-41** The UI never builds SQL. New data needs mean a new named query.
- **VIEW-42** Offsets from the store are code points; the reader converts to UTF-16 once
  per segment.

## 7. Static export

```
dist/ops/
├── index.html            # app; opens from file:// with a double-click
├── assets/               # JS and CSS, classic (non-module) bundles
└── data/
    ├── store.js          # window.__MOSAIC_DB__ = "<base64 of the scoped SQLite>"
    └── sqlite-wasm.js    # the WASM binary as base64
```

- **VIEW-50** Works opened from `file://` in current Chrome, Edge and Firefox with no
  server. Browsers block `fetch()` and module scripts from `file://`, so data and WASM
  travel as classic scripts and the WASM is instantiated from bytes. **Spike S2 in M0**
  proves this with `@sqlite.org/sqlite-wasm` (FTS5 included) before anything else is
  built on it; fallback if it fails: a JSON bundle plus a small in-browser search index.
- **VIEW-51** `--single-file` inlines everything into one `index.html` (for e-mail or
  data packs), accepted up to 50 MB.
- **VIEW-53** Any scope exports the same way, however small. An export of the SW ICD alone
  (`export: {sources: [icd], types: []}`) is still one offline folder or one HTML file
  with search; its mentions are plain text because no entities travel.
- **VIEW-52** The export shows a footer line: project, view, store content hash, build
  date.

## 8. Theme

- **VIEW-60** All colours, radii and spacing are CSS custom properties. Presets:
  `corporate` (default) and `neutral`. Both have light and dark variants following the OS
  setting, with a manual toggle.
- **VIEW-61** `corporate` follows the MOSAIC design system, copied read-only into
  `design/mosaic/` from <https://claude.ai/artifact/LwLFNqDsgwtSAvM7r8aans> and applied
  as described in `design/viewer-guidelines.md`: its `tokens.json` colours and
  type, the "last shard" mark (`mosaic-mark-dark` on the navy header, `mosaic-app-icon-*`
  as favicon) and the uppercase MOSAIC wordmark. Colour keeps its system meaning: blues
  for reference data (SRDB, FOPs, code), terracotta for documents, turquoise for
  telemetry, saffron for warnings and AI proposals, majolica for errors. The blues stay
  placeholders until the corporate values are confirmed (Q6); swapping them means editing
  the tokens only. The static export of a customer data pack uses the MOSAIC Tessera
  marks instead.
- **VIEW-64** The theme's CSS variables are generated from `design/mosaic/tokens.json` at
  build time. No colour literal appears in `viewer/src` outside that generated file (a
  test enforces it, DG-01), so replacing the placeholder blues means replacing the tokens
  file only.
- **VIEW-63** Fonts are bundled with the viewer (IBM Plex Sans and Mono, SIL OFL, as the
  design system's stand-in for the corporate face), so the offline rule (VIEW-02) holds.
- **VIEW-62** Text contrast meets WCAG 2.2 AA in all presets and modes.

## 9. Live server (`mosaic-server`)

- **VIEW-70** FastAPI app: `GET /api/meta`, `GET /api/q/{name}` (parameters validated
  against the query header), static viewer files. SQLite opened `mode=ro`.
- **VIEW-71** Binds to `127.0.0.1` by default; `--host` to share on a network.
- **VIEW-72** With `--watch`, the server rebuilds on source change; the viewer polls
  `/api/meta` every 2 s and reloads the current route when `content_hash` changes.

## 10. Quality and performance

- **VIEW-80** Unit tests (Vitest) for the data layer, offset conversion, path syntax and
  view merging; component tests for reader rendering of each segment kind.
- **VIEW-81** Playwright e2e on the demo mission in both modes, with the same scenarios:
  open FOP-PWR-001 → click `PWRC0101` → panel shows *Sent by* and *Handled by* → click
  *Described in* → manual section highlighted → back restores the FOP.
- **VIEW-82** Small export: first content in < 1.5 s from `file://`; panel update after a
  click < 100 ms; tables stay smooth at 10,000 rows (virtualised).
- **VIEW-83** Keyboard-only run of the VIEW-81 scenario passes; axe checks report no
  serious issues.

## 11. Stack

Svelte 5, Vite, TypeScript (strict), `svelte-check`, ESLint, Prettier, Vitest,
Playwright, `@sqlite.org/sqlite-wasm`, `highlight.js` core with the C and Python grammars.
No component library: components are handwritten against the theme tokens, which keeps
the bundle small and offline-safe. Node LTS, npm, lockfile committed.

The clickable prototype (`prototype/index.html`) illustrates the ops view with a slice of
the demo mission. It is a sketch, not the implementation, and is not maintained once the
real viewer runs.
