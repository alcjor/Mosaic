# 04 — Mocker

Status: draft 0.1 · Package: `mosaic-mock` (import `mosaic_mock`) · CLI: `mosaic-mock`

The mocker invents a complete, consistent system and writes it out as the files a real
project would have, together with a **ground truth**: every link that should be found,
every defect that was injected and how it should be detected. It is the test oracle and
the demo data.

## 1. Principles

- **MOCK-01** Independent of the system under test: `mosaic_mock` never imports
  `mosaic_core`, `mosaic_extractors`, `mosaic_server` or `mosaic_cli` (import-linter
  contract). Shared bugs would otherwise hide themselves.
- **MOCK-02** Deterministic: same profile, size, seed, defect set and mocker version give
  byte-identical files.
- **MOCK-03** Generic engine, domain profiles. The engine knows items, edges, artifacts,
  placements and defects; a profile knows what a spacecraft is.
- **MOCK-04** Everything is invented. No real mission names, IDs or document text.
- **MOCK-05** Two profiles ship: `spacecraft` (demo and pack tests) and `toy` (feeds the
  core's genericity tests, CORE-06).

## 2. Engine

```
profile.build_world(rng, size)  →  World (items + edges)
renderers(world)                →  Artifacts (files) + Placements (where each reference was written)
defects(world, artifacts)       →  mutated Artifacts + Defect records
writer                          →  output folder + ground_truth.json
```

| Concept | Description |
|---|---|
| `World` | Domain-neutral graph: `Item(type, key, attrs)` and `Edge(type, from, to)` |
| `Rng` | Named, independent streams derived from `(seed, stream name)`, so adding a stream never reshuffles another (stable snapshots) |
| `Naming` | Toolkit for ID schemes, mnemonic vocabularies, uniqueness and edit-distance-safe IDs (no two IDs within distance 1, so typo defects stay unambiguous) |
| `Renderer` | Writes one artifact kind (tables, HTML, `.docx`, PDF, C, Python) and returns its placements |
| `Placement` | `(file, locator, surface, item, role, match)`: one reference written somewhere |
| `DefectInjector` | Mutates an artifact or the world before rendering and returns a `Defect` record |
| `TextGen` | Jinja templates for prose; optional LLM rewrite (§ 6) |

```python
class Profile(Protocol):
    name: str
    sizes: Mapping[str, SizeSpec]  # small, medium, large

    def build_world(self, rng: Rng, size: SizeSpec) -> World: ...
    def renderers(self) -> Sequence[Renderer]: ...
    def defect_injectors(self) -> Mapping[str, DefectInjector]: ...
```

Profiles live in `mosaic_mock/profiles/<name>/` with their templates and vocabularies.

## 3. Ground truth

`ground_truth.json`, validated by a JSON Schema shipped with the mocker.

```json
{
  "profile": "spacecraft", "size": "small", "seed": 42, "mocker_version": "0.1.0",
  "items":   [{"type": "PCF", "key": "PWRT0012", "attrs": {"PCF_DESCR": "BAT_V_MAIN"}}],
  "mentions": [
    {"file": "fops/fop_pwr_001.py", "loc": "line=14", "surface": "PWRC0101",
     "item": "CCF/PWRC0101", "role": "sends", "match": "exact"},
    {"file": "sum/sum.docx", "loc": "section=4.1", "surface": "main battery voltage",
     "item": "PCF/PWRT0012", "role": "mentions", "match": "fuzzy_only"}
  ],
  "xrefs": [
    {"type": "described_in", "from": {"file": "fops/fop_pwr_001.py", "scope": "step=2"},
     "to": {"file": "sum/sum.docx", "scope": "section=4.2"}}
  ],
  "defects": [
    {"id": "D01-0001", "kind": "typo_in_reference", "file": "sum/sum.docx", "loc": "section=4.1",
     "original": "PWRT0012", "mutated": "PWRT0O12", "expected_detection": "v1:unresolved_reference"}
  ]
}
```

- **MOCK-10** Locators are deliberately coarse and format-independent: `line=<n>` for code
  and scripts, `section=<number>` for documents and HTML, `table=<TABLE>,row=<n>` for SRDB
  files. The e2e test maps store mentions onto the same tuples and compares multisets.
- **MOCK-11** `match` is `exact` (an exact matcher must find it) or `fuzzy_only` (written
  as a long description or paraphrase; v1 must *not* link it, a future matcher should).
  This gives the future fuzzy/AI matcher a ready benchmark.
- **MOCK-12** Every ground-truth mention is checked against its artifact by the mocker's
  own minimal readers: the surface occurs at the locator.

## 4. CLI

```
mosaic-mock generate --profile spacecraft --size small --seed 42 \
                     --defects none|default|all|<file.yaml> \
                     [--llm <provider>] [--date 2026-01-01] --out examples/demosat-1
mosaic-mock list-profiles
mosaic-mock list-defects --profile spacecraft
```

- **MOCK-15** `--size` accepts a preset or `--scale <float>` on top of one.
- **MOCK-16** The output folder also gets a ready `mosaic.yaml` pointing at the generated
  files, so `mosaic build examples/demosat-1/mosaic.yaml` works with no editing.
- **MOCK-17** `examples/demosat-1/` (small, clean, seed 42) is committed so the files can
  be browsed without running anything; CI regenerates it and fails on any difference.

## 5. Spacecraft profile: DEMOSAT-1

### 5.1 World

| | small (default) | medium | large |
|---|---|---|---|
| Subsystems | 6: PWR, TCS, AOC, OBC, COM, PLD | 10 | 14 |
| TM parameters (PCF) | ~80 | ~1,000 | ~5,000 |
| Telecommands (CCF) | ~30 | ~400 | ~2,000 |
| TM packets (PID) | 8: one HK per subsystem + 2 event | ~40 | ~150 |
| FOPs | 6 | 30 | 100 |
| Manual length | ~25 pages | ~150 | ~500 |
| C files | ~14 | ~60 | ~200 |

- PUS-C services used: 1, 3, 5, 8, 17, 20. HK packets are (3,25), events (5,x), most TCs
  (8,1) function management, plus (3,5)/(3,6), (17,1), (20,1)/(20,3).
- Parameters: analogue (with numerical calibration, ~30% with limit checks) and status
  (with textual calibration, e.g. `OFF`/`ON`, mode names).
- TCs: 0–3 arguments (CPC), each with type and range.
- Naming (default `esa-like`, configurable like mibgen's styles): `PCF_NAME` `<SS>T<NNNN>`
  (`PWRT0012`), `CCF_CNAME` `<SS>C<NNNN>` (`PWRC0101`), `CPC_PNAME` `<SS>P<NNNN>`
  (`PWRP0001`); mnemonics in `PCF_DESCR`/`CCF_DESCR` (`BAT_V_MAIN`, `PWR_HTR_A_ON`);
  English long description in the custom column `PCF_LDESCR` ("Main battery voltage").

### 5.2 Artifacts

| File(s) | Renderer | Content |
|---|---|---|
| `srdb/*.dat` | `scos_tables` | Tables of `02` § 3 in ICD column order, tab-separated, custom trailing column `PCF_LDESCR`, plus `vdf.dat`. The mocker carries its own column specs (MOCK-01); a test checks they match the pack's |
| `icd/scsw_icd.html` | `icd_html` | § 1 TM packets: one `h3` per packet (SPID, APID, service) and a table *Offset · Parameter · Mnemonic · PTC/PFC · Description*. § 2 Telecommands: one `h3` per TC (`PWRC0101 PWR_HTR_A_ON`) and an argument table |
| `sum/sum.docx`, `sum/sum.pdf` | `manual` | One document model rendered twice. 1 Introduction, 2 SCSW overview, 3 PUS services, then one chapter per application: *n*.1 Overview (prose with IDs, mnemonics and long descriptions), *n*.2 Telecommands (table *TC · Mnemonic · Description · Arguments*), *n*.3 Housekeeping (table *Parameter · Mnemonic · Unit · Description*), *n*.4 Operations notes; appendix of acronyms. Real heading styles and tables in `.docx`; bookmarks in PDF |
| `scsw/include/demosat_ids.h` | `c_code` | `#define PARAM_PWRT0012 (0x0C12u) /* BAT_V_MAIN */` |
| `scsw/include/demosat_tc_ids.h` | `c_code` | `typedef enum { TC_PWRC0101 = 0x0101u, ... } tc_id_t;` |
| `scsw/src/<ss>_app.c/.h` | `c_code` | Per application: `<ss>_tc_dispatch()` with `case TC_PWRC0101:` labels calling static handlers, `<ss>_hk_fill()` using `PARAM_` ids, comments naming mnemonics |
| `fops/fop_<ss>_<nnn>.py` | `fops` | Module docstring `FOP-PWR-001 Battery heater activation` with purpose and preconditions; steps as `@step(n, "title")` functions calling `send_tc`, `verify_tm`, `get_tm`, `wait` from an invented `demoproc` API |
| `mosaic.yaml` | `project` | Project config for the pack (MOCK-16) |
| `ground_truth.json` | engine | § 3 |

FOP example (small mission, seed 42):

```python
"""FOP-PWR-001 Battery heater activation

Purpose: switch on battery heater A when the battery is cold.
Preconditions: BAT_V_MAIN (PWRT0012) above 26 V.
"""

from demoproc import step, send_tc, verify_tm, wait


@step(1, "Check battery voltage")
def step_1():
    verify_tm("PWRT0012", ">", 26.0)  # BAT_V_MAIN


@step(2, "Switch heater A on")
def step_2():
    send_tc("PWRC0101", PWRP0001=1)  # PWR_HTR_A_ON, thermostat mode
    wait(5)
    verify_tm("PWRT0031", "==", "ON")  # HTR_A_STAT
```

## 6. Prose: templates, optional LLM

- **MOCK-20** Default text comes from Jinja templates and vocabularies: offline,
  deterministic, no API key.
- **MOCK-21** `--llm <provider>` rewrites template paragraphs for realism. References are
  passed as protected tokens (`⟦PCF/PWRT0012:id⟧`) that must come back unchanged; if any is
  lost or altered, the template text is kept and a warning logged. Ground truth is
  computed after substitution, so it stays exact.
- **MOCK-22** LLM responses are cached by prompt hash in `mock-cache/<profile>/` and
  committed, so a generation with `--llm` is reproducible without network. Providers are
  an optional extra (`mosaic-mock[llm]`); only invented data is ever sent.

## 7. Defects

Selected with `--defects`. The `default` set injects one of each v1-detectable kind plus
two `future` ones; `all` injects every kind at configurable rates.

| Id | Kind | Where | Expected detection |
|---|---|---|---|
| D01 | `typo_in_reference` (one-character edit, e.g. `0`→`O`) | manual, ICD, code comment, FOP | `v1:unresolved_reference` (with the original as a suggestion) |
| D02 | `stale_reference` (parameter renamed in SRDB, documents keep the old ID) | manual, FOP | `v1:unresolved_reference` |
| D03 | `deleted_item_reference` (TC removed from SRDB, a FOP still sends it) | FOP | `v1:unresolved_reference`, severity error |
| D04 | `case_variant` (`pwrt0012`) | manual | `v1:unresolved_reference` with the default case-sensitive config |
| D05 | `missing_fields` (row shorter than the mandatory columns) | SRDB | `v1:missing_fields` |
| D06 | `extra_fields` (undeclared trailing column) | SRDB | `v1:extra_fields` |
| D07 | `duplicate_key` | SRDB | `v1:duplicate_key` |
| D08 | `dangling_foreign_key` (PLF row naming a missing parameter) | SRDB | `v1:broken_relation` |
| D09 | `unit_mismatch` (manual table says mA, SRDB says A) | manual | `future` (consistency report) |
| D10 | `id_value_mismatch` (`#define` value differs from `PCF_PID`) | code | `future` |
| D11 | `orphan_parameter` (in PCF, in no packet, never mentioned) | SRDB | `future` |

- **MOCK-25** Each defect is recorded with original and mutated text and its locator; the
  ground-truth mention it replaces is removed or downgraded accordingly.
- **MOCK-26** Defects never collide: one defect per locator, and typo results are checked
  not to equal another valid ID.

## 8. Determinism details

- **MOCK-30** `.docx`: fixed core properties (dates from `--date`), zip entries written in
  a fixed order with fixed timestamps. PDF: ReportLab `invariant=1`. HTML, C, Python and
  `.dat`: no timestamps; `\n` line endings; UTF-8.
- **MOCK-31** No use of the global `random` module, `set` iteration order or the clock.

## 9. Tests

- **MOCK-40** Determinism: two generations hash equal; golden hashes per (profile, size,
  seed) are updated only on purpose.
- **MOCK-41** Validity: `.dat` rows have the column counts of the mock's spec; `.docx`
  reopens with python-docx; PDF text extracts with `pypdf`; FOPs `ast.parse`; C parses
  with tree-sitter-c without error nodes (test-only dependency).
- **MOCK-42** Ground truth self-check (MOCK-12) for every placement.
- **MOCK-43** Every injector, run alone on the small world, changes exactly the recorded
  locator.
- **MOCK-44** Small generation takes under 5 s.

## 10. Dependencies

`jinja2`, `python-docx`, `reportlab`; test-only `pypdf`, `tree-sitter`, `tree-sitter-c`;
optional extra `llm`. All permissive licences (D14).
