# 01 — Core (domain-neutral)

Status: draft 0.1 · Package: `mosaic-core` (import `mosaic_core`) plus `mosaic-extractors`

The core knows nothing about spacecraft. It knows sources, entities, segments, mentions,
relations, cross-references, diagnostics and views. A system pack supplies the meaning.

## 1. Principles

- **CORE-01** The core and the generic extractors contain no domain vocabulary. A test
  fails if `mosaic_core` or `mosaic_extractors` source contains any word from a deny list
  (`SCOS`, `MIB`, `SRDB`, `PCF`, `telecommand`, `telemetry`, `spacecraft`, `FOP`, `PUS`).
- **CORE-02** Read-only: no command writes to a source file.
- **CORE-03** Provenance everywhere: every entity, segment, mention and diagnostic records
  its source and a location (file, line/page/xpath/row, character span).
- **CORE-04** Deterministic builds: same inputs, config and Mosaic version produce a
  byte-identical store, apart from the `meta.built_at` row.
- **CORE-05** The store is the contract. The viewer, notebooks and future Mosaic tools
  read the store; none of them import extractor code.
- **CORE-06** The core test suite runs against a non-space toy pack (`packs/_toy/`) so the
  genericity claim is tested, not asserted.

## 2. Configuration model

Four layers, all YAML except the schemas, all validated before anything is extracted.

| Layer | Owner | File(s) | Contents |
|---|---|---|---|
| Core schema | Mosaic | `mosaic_core/schema/core.yaml` (LinkML) | The classes in this spec: Source, Entity, Segment, Mention, Relation, Xref, Diagnostic, View, PackConfig, ProjectConfig |
| System schema | Pack | `packs/<pack>/schema.yaml` (LinkML) | Entity classes, their slots, keys, relations, Mosaic annotations |
| Pack config | Pack | `packs/<pack>/pack.yaml` + `views/*.yaml` | Source kinds, extractor bindings, link rules, cross-reference rules, relation rules, views |
| Project config | User | `mosaic.yaml` | Which pack, where the files are, per-project overrides |

- **CORE-10** The core schema is written in LinkML. Pydantic models are generated from it
  (`gen-pydantic`) and committed; CI fails if regenerating changes them.
- **CORE-11** Config files are validated against the generated models. Errors name the
  file, the YAML path and what was expected. `mosaic check` runs validation only.
- **CORE-12** The system schema is plain LinkML plus a small annotation vocabulary
  (below). Mosaic never requires a pack to write Python.

### 2.1 System schema annotations

| Annotation | On | Meaning |
|---|---|---|
| `identifier: true` or `unique_keys` | class/slot (standard LinkML) | Entity key. Composite keys are joined with `\|` |
| slot `range: <Class>` | slot (standard LinkML) | A relation, resolved by the target's key |
| `mosaic.label_slot` | class | Slot used as the entity's display label |
| `mosaic.surface_form` | slot | Values of this slot are matchable text (IDs, mnemonics) |
| `mosaic.id_pattern` | class | Regex for tokens that *look like* this type's IDs; used to report unresolved references |
| `mosaic.case_sensitive` | class | Default `true` |
| `mosaic.normalize` | slot | `none` (default), `upper`, or `int` (so `0x0C12`, `3090` and `0C12h` compare equal) |
| `mosaic.range_by` | slot | Polymorphic relation: target class chosen by another slot's value, e.g. `{slot: PCF_CATEG, map: {N: CAF, S: TXF}}` |
| `mosaic.text_slot` | slot | Included in full-text search |

Minimal example (from the toy pack):

```yaml
id: https://example.org/mosaic/toy
name: toy
prefixes: {linkml: https://w3id.org/linkml/}
imports: [linkml:types]
default_range: string
classes:
  Part:
    annotations: {mosaic.label_slot: part_name, mosaic.id_pattern: '\bP-\d{3}\b'}
    slots: [part_id, part_name, supplier]
  Supplier:
    slots: [supplier_id, supplier_name]
slots:
  part_id: {identifier: true, annotations: {mosaic.surface_form: true}}
  part_name: {annotations: {mosaic.surface_form: true, mosaic.text_slot: true}}
  supplier: {range: Supplier}
  supplier_id: {identifier: true}
  supplier_name: {annotations: {mosaic.text_slot: true}}
```

### 2.2 Project config

```yaml
# mosaic.yaml
pack: ../packs/spacecraft          # path or installed pack id
project: DEMOSAT-1
output: build/demosat-1.mosaic.sqlite
sources:
  srdb:   {path: data/srdb/, options: {icd_issue: "7.0", custom_columns: {pcf: [PCF_LDESCR]}}}
  icd:    {path: data/scsw_icd.html}
  sum:    {path: [data/sum.docx]}
  code:   {path: data/scsw/, include: ["**/*.c", "**/*.h"]}
  fops:   {path: data/fops/, include: ["**/*.py"]}
xref_maps:                          # project-specific explicit maps (see § 6.3)
  code-file-to-manual:
    - {from: {source: code, path_glob: "src/pwr_*.c"}, to: {source: sum, heading_regex: '^\d+(\.\d+)* Power'}}
```

- **CORE-13** A project may override any pack option it declares as overridable; it may
  not add link rules (those belong in the pack). Rationale: packs stay comparable across
  missions.

## 3. Pipeline

`mosaic build` runs these stages in order. Each stage is a pure function of the previous
stage's output plus config, which makes it testable alone.

1. **Load** pack, system schema and project config; validate (CORE-11).
2. **Extract** every source with its extractor → entities, segments, regions (§ 4).
3. **Resolve relations** declared in the system schema (slot ranges) → relations, or
   `broken_relation` diagnostics.
4. **Match** regions against the surface-form index with the link rules → mentions (§ 5).
5. **Derive** relations promoted from mentions and cross-references (§ 6).
6. **Collect external refs** from registered external data providers (§ 9.5; none in v1).
7. **Write** the store (§ 8) and the build report.

- **CORE-20** The build report (`<output>.report.json` and a console summary) lists counts
  per source, entity type, role and diagnostic code, and the stage timings.
- **CORE-21** `mosaic build` exits non-zero only on config errors or unreadable sources.
  Diagnostics never fail a build; `--fail-on error` makes them fail it (for CI).

## 4. Extraction

```python
class Extractor(Protocol):
    name: str

    def extract(self, src: SourceInput, ctx: ExtractContext) -> ExtractResult: ...


@dataclass(frozen=True)
class ExtractResult:
    entities: list[EntityRecord]
    segments: list[SegmentRecord]  # a tree, via parent ids
    regions: list[Region]  # text spans with context tags, input to matching
    diagnostics: list[DiagnosticRecord]
```

A **region** is a span of a segment's text plus **context tags** describing what the text
is. Link rules select regions by tags, which is what makes matching configurable without
code.

```python
@dataclass(frozen=True)
class Region:
    segment_id: str
    start: int
    end: int  # code points into the owning segment's text
    kind: str  # e.g. paragraph, heading, table_cell, comment, call_arg
    tags: Mapping[str, str]  # e.g. {"header": "Name", "level": "2", "func": "send_tc", "arg": "0"}
```

### 4.1 Generic extractors (package `mosaic-extractors`)

| Extractor | Input | Emits | Region kinds and tags |
|---|---|---|---|
| `delimited` | Headerless or headed delimited text (tab, `\|`, `,`) | One entity per row of the configured class; column spec from options | none (record source) |
| `html` | HTML page | Segment tree from headings, paragraphs, lists, tables | `heading{level}`, `paragraph`, `list_item`, `table_cell{header,col,table_caption}` |
| `docx` | Word `.docx` | Same tree as `html`, via heading styles and tables | same as `html`, plus `caption` |
| `pdf` | Text PDF | Pages → blocks; headings by numbering pattern and font size | same as `html`, plus `page` tag on every region |
| `c` | C sources and headers (tree-sitter) | File segments, function segments; optional entities for functions and constants | `comment`, `define_name`, `define_value`, `enum_constant`, `case_label`, `string_literal`, `identifier`, each with `function` tag when inside one |
| `python` | Python scripts (stdlib `ast` + `tokenize`, never executed) | File segments; segments for module docstring and configured step functions | `docstring`, `comment`, `call_arg{func,arg}` (positional string argument), `call_kw{func}` (keyword name), `string_literal`, each with `step` tag when inside a step |

- **CORE-30** `delimited` supports: column lists by version from pack data files;
  mandatory vs optional columns; declared custom trailing columns; diagnostics
  `missing_fields`, `extra_fields` (undeclared trailing columns), `bad_value` (type/enum
  check from the schema), `duplicate_key`.
- **CORE-31** `html` and `docx` produce the same segment tree for the same logical
  document, so a manual renders identically whichever format was given.
- **CORE-32** `html` strips scripts, styles and event attributes. Stored rich text is
  limited to an allowlist of marks: bold, italic, code, superscript, subscript, external
  link.
- **CORE-33** `c` and `python` never compile, import or execute the code.
- **CORE-34** Extractors that emit entities from text (e.g. one `Function` entity per C
  function definition) link the entity to its segment.
- **CORE-35** Each extractor has a shared contract test: given a fixture, it produces
  stable ids, valid spans (`0 ≤ start < end ≤ len(text)`), and a tree whose every parent
  exists.

## 5. Matching

### 5.1 Surface-form index

Built after extraction from every entity slot annotated `mosaic.surface_form`. Each entry
maps a string to `(entity type, entity id, slot)`. One string may map to several entities
(ambiguity is kept and reported, never resolved silently).

### 5.2 Link rules

```yaml
link_rules:
  - id: fop-sends-tc
    sources: [fops]
    where: {kind: call_arg, func: [send_tc], arg: "0"}
    target: {types: [CCF], match_on: [CCF_CNAME]}
    role: sends
    priority: 20
  - id: code-define-param
    sources: [code]
    where: {kind: define_name}
    extract: '^PARAM_(?P<ref>[A-Z0-9]+)$'     # match only the named group
    target: {types: [PCF], match_on: [PCF_NAME]}
    role: defines_id
    priority: 20
  - id: text-mentions
    sources: all
    where: {kind: [paragraph, heading, list_item, table_cell, comment, docstring]}
    target: {types: [PCF, CCF]}               # all surface-form slots of these types
    role: mentions
    priority: 0
```

- **CORE-40** Matching goes through `Matcher`:
  ```python
  class Matcher(Protocol):
      name: str

      def match(
          self, region: Region, text: str, rule: LinkRule, index: SurfaceIndex
      ) -> Iterable[MentionCandidate]: ...
  ```
  v1 ships `exact` only. A rule may name its matcher (`matcher: exact` is the default).
  Candidates carry `confidence` (1.0 for exact) and `matcher`, so later fuzzy or AI
  matchers add rows without a schema change, and the UI can show their status.
- **CORE-41** `exact` finds surface forms bounded by non-identifier characters
  (`boundary: identifier`, default) or word characters (`boundary: word`), honouring
  `mosaic.case_sensitive`. Multi-token forms are found with a trie; no external
  dependency.
- **CORE-42** With `extract`, the regex runs on the region text and only the `ref` group
  is looked up; the mention span is the group's span.
- **CORE-43** One span gets one mention: the highest `priority` rule wins; ties go to the
  rule listed first. Overlapping candidates keep the longest.
- **CORE-44** Unresolved references: inside regions selected by any rule, tokens matching
  a target type's `mosaic.id_pattern` but absent from the index become mentions with no
  entity (`status: unresolved`) plus an `unresolved_reference` diagnostic with up to three
  suggestions (same type, edit distance ≤ 2). Suggestions are hints, never links.
- **CORE-45** Ambiguous matches (one string, several entities) become one mention per
  candidate with `status: ambiguous` and an `ambiguous_reference` diagnostic.

## 6. Relations and cross-references

### 6.1 Schema relations

- **CORE-50** Every slot whose range is a class (or whose target is chosen by
  `mosaic.range_by`) becomes a relation named after the slot, from the row's entity to the
  target found by key. Empty values produce nothing; a missing target produces a
  `broken_relation` diagnostic and no relation.

### 6.2 Relations promoted from mentions

```yaml
relation_rules:
  - id: function-handles-tc
    from_mentions: {roles: [handles]}
    subject: enclosing_entity        # the entity whose segment encloses the mention (e.g. a C function)
    type: handles
```

- **CORE-51** Promoted relations record the rule id and the mention they came from.

### 6.3 Cross-references (segment ↔ segment)

Two rule shapes:

```yaml
xref_rules:
  - id: fop-step-described-in-manual
    type: described_in
    via: entity                                  # both sides refer to the same entity
    from: {sources: [fops], roles: [sends, reads], scope: step}
    to:   {sources: [sum, icd], roles: [describes]}
  - id: code-file-to-manual
    type: documented_in
    via: explicit_map                            # pairs listed in the project's xref_maps
    fallback: {via: entity, min_shared: 2, from_roles: [handles, defines_id], to_roles: [describes]}
```

- **CORE-52** `via: entity` links the *scope* segments (§ 8: the smallest structural
  segment containing the mention: section, step, function or file) and records the shared
  entity. Duplicate pairs are merged, keeping every shared entity.
- **CORE-53** `via: explicit_map` reads pairs from the project config (path globs and
  heading regexes). If none match and a `fallback` is given, the fallback applies.

## 7. Diagnostics

| Code | Severity | Raised by |
|---|---|---|
| `missing_fields` | error | `delimited` |
| `extra_fields` | warning | `delimited` |
| `bad_value` | warning | `delimited` |
| `duplicate_key` | error | any record source |
| `broken_relation` | error | relation stage |
| `unresolved_reference` | warning (error if role is `sends`) | matching |
| `ambiguous_reference` | warning | matching |
| `unparsable_source` | error | any extractor |

- **CORE-55** Severity per code is overridable in the pack (`diagnostics: {unresolved_reference: {role_sends: error}}`).

## 8. Store (SQLite)

One file, `*.mosaic.sqlite`, opened read-only by every consumer.

```sql
CREATE TABLE meta        (key TEXT PRIMARY KEY, value TEXT NOT NULL);
  -- store_version, mosaic_version, pack_id, pack_version, project, content_hash, built_at
CREATE TABLE source      (id TEXT PRIMARY KEY, name TEXT, kind TEXT, extractor TEXT,
                          path TEXT, sha256 TEXT, n_files INTEGER);
CREATE TABLE entity      (id INTEGER PRIMARY KEY, type TEXT NOT NULL, key TEXT NOT NULL,
                          label TEXT, source_id TEXT REFERENCES source(id),
                          segment_id TEXT REFERENCES segment(id), location TEXT,
                          attrs TEXT NOT NULL,                  -- JSON object
                          UNIQUE (type, key));
CREATE TABLE relation    (id INTEGER PRIMARY KEY, type TEXT NOT NULL,
                          from_id INTEGER REFERENCES entity(id), to_id INTEGER REFERENCES entity(id),
                          origin TEXT NOT NULL,                 -- schema | rule:<id>
                          mention_id INTEGER REFERENCES mention(id), attrs TEXT);
CREATE TABLE segment     (id TEXT PRIMARY KEY, source_id TEXT REFERENCES source(id),
                          parent_id TEXT REFERENCES segment(id), ordinal INTEGER NOT NULL,
                          kind TEXT NOT NULL, title TEXT,
                          text TEXT,                            -- only on text-owning segments
                          marks TEXT,                           -- JSON [[start,end,mark],...]
                          scope INTEGER NOT NULL DEFAULT 0,     -- 1 = section/step/function/file
                          locator TEXT);                        -- JSON: file, page, line range, xpath
CREATE TABLE mention     (id INTEGER PRIMARY KEY, segment_id TEXT REFERENCES segment(id),
                          scope_segment_id TEXT REFERENCES segment(id),
                          start INTEGER NOT NULL, "end" INTEGER NOT NULL, surface TEXT NOT NULL,
                          entity_id INTEGER REFERENCES entity(id),  -- NULL when unresolved
                          status TEXT NOT NULL,                 -- resolved | unresolved | ambiguous
                          role TEXT NOT NULL, rule_id TEXT NOT NULL,
                          matcher TEXT NOT NULL, confidence REAL NOT NULL);
CREATE TABLE xref        (id INTEGER PRIMARY KEY, type TEXT NOT NULL, rule_id TEXT NOT NULL,
                          from_segment TEXT REFERENCES segment(id), to_segment TEXT REFERENCES segment(id),
                          via_entities TEXT);                   -- JSON list of entity ids
CREATE TABLE diagnostic  (id INTEGER PRIMARY KEY, code TEXT NOT NULL, severity TEXT NOT NULL,
                          source_id TEXT, segment_id TEXT, mention_id INTEGER,
                          location TEXT, message TEXT NOT NULL, data TEXT);
CREATE TABLE external_ref(id INTEGER PRIMARY KEY, entity_id INTEGER REFERENCES entity(id),
                          provider TEXT NOT NULL, kind TEXT NOT NULL, locator TEXT NOT NULL);
CREATE VIRTUAL TABLE segment_fts USING fts5(title, text, content='segment', content_rowid='rowid');
CREATE VIRTUAL TABLE entity_fts  USING fts5(key, label, body, content='');
```

- **CORE-70** Offsets are Unicode code points into `segment.text`. The viewer converts
  them (JavaScript strings are UTF-16). A test covers a non-BMP character.
- **CORE-71** Mentions attach to the text-owning segment; `scope_segment_id` is the
  smallest enclosing segment with `scope = 1`. Code and scripts own text at file level, so
  the reader shows whole files and functions/steps are scopes inside them.
- **CORE-72** For every entity type, a SQL view `t_<Type>` exposes its attributes as typed
  columns (generated from the system schema), so notebooks and SQL users get ordinary
  tables.
- **CORE-73** `store_version` is semver. Consumers refuse a store with a different major
  version. Stores are build artifacts: there are no migrations, you rebuild.
- **CORE-74** Ids are stable across rebuilds when sources are unchanged: segment ids are
  `<source>:<path>#<structural path>`; entity integer ids follow `(type, key)` sort order.

## 9. Interfaces for consumers and plug-ins

### 9.1 Named queries

All reads by the viewer go through named SQL queries in `queries/*.sql` at the repo root.
Each file holds one statement and a header declaring its parameters and result columns.

- **CORE-80** Python (live server, notebook API) and TypeScript (static export, WASM
  SQLite) execute the same files. A contract test runs every query against the demo store
  in both runtimes and compares results.
- **CORE-81** v1 queries: `meta`, `sources`, `source_tree`, `segment_page`,
  `entity_by_key`, `entity_relations`, `entity_mentions`, `segment_xrefs`,
  `entity_xrefs`, `table_page`, `search`, `diagnostics`.

### 9.2 Python read API

```python
from mosaic_core import Store

s = Store.open("build/demosat-1.mosaic.sqlite")
tc = s.entity("CCF", "PWRC0101")
s.mentions(tc, roles=["sends"])  # list of Mention
s.query("table_page", type="PCF", limit=50)
s.sql("SELECT * FROM t_PCF WHERE PCF_UNIT = 'V'")
```

- **CORE-85** The API returns plain dataclasses; `to_pandas()` works when pandas is
  installed and is not a dependency.

### 9.3 Plug-in registration

- **CORE-90** Extractors, matchers, derivers, exporters and external data providers
  register through entry points (`mosaic.extractors`, `mosaic.matchers`,
  `mosaic.derivers`, `mosaic.exporters`, `mosaic.external_providers`). Built-ins use the
  same mechanism.

### 9.4 Exporters

- **CORE-91** `Exporter` takes a store and a view and writes an output folder. v1 ships
  `static-viewer` (see `03-viewer.md`). SysML v2 later uses the same interface.

### 9.5 Telemetry hook (interface only)

```python
@dataclass(frozen=True)
class ExternalRef:
    provider: str  # e.g. "mission-timeseries"
    kind: str  # e.g. "timeseries"
    locator: Mapping[str, str]  # e.g. {"series": "PWRT0012"}


class ExternalDataProvider(Protocol):
    id: str

    def refs_for(self, entity: EntityView) -> Iterable[ExternalRef]: ...
```

- **CORE-60** The `external_ref` table, the protocol and the `external_providers:` config
  key exist in v1. No provider ships and the viewer shows nothing. A test with a fake
  provider proves refs reach the store.

## 10. CLI (package `mosaic-cli`)

| Command | Does |
|---|---|
| `mosaic check [mosaic.yaml]` | Validate pack and project config |
| `mosaic build [mosaic.yaml]` | Run the pipeline, write store and report |
| `mosaic diagnostics <store> [--code ..] [--severity ..]` | Print diagnostics |
| `mosaic serve <store> [--view ops] [--watch mosaic.yaml]` | Live viewer on localhost; `--watch` rebuilds on source change |
| `mosaic export <store> --view <id> --out <dir> [--single-file]` | Static offline viewer for a view's scope |
| `mosaic demo` | Generate the mock mission, build, serve, open the browser |

## 11. Non-functional requirements

- **CORE-95** Build time: small demo mission < 10 s; a realistic mission (~5,000
  parameters, ~2,000 TCs, ~100 FOPs, a 500-page manual, ~200 C files) < 2 min on a
  standard laptop.
- **CORE-96** No network access during build, serve or export.
- **CORE-97** Size limits per source file (default 200 MB) with a clear diagnostic.
- **CORE-98** Logging via the standard library; `--verbose` shows per-stage detail; no
  print statements outside the CLI.
