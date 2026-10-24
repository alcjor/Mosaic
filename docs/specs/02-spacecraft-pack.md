# 02 — Spacecraft pack: the connected user manual

Status: draft 0.1 · Folder: `packs/spacecraft/` (configuration and templates, no Python)

This pack turns the core into the connected user manual for an on-board software (SCSW):
the SRDB, the SW ICD, the SW user manual, the SCSW code and the FOPs, all linked.

- **PACK-01** The pack contains only LinkML, YAML and data files. If something cannot be
  expressed without code, the gap is fixed in the core as a generic feature, never with
  pack-specific Python.

## 1. Layout

```
packs/spacecraft/
├── pack.yaml              # sources, link rules, xref rules, relation rules, diagnostics policy
├── schema.yaml            # LinkML system schema: SRDB tables + Function
├── srdb/icd/7.0.yaml      # column specs per table for one Import ICD issue (one file per issue)
├── views/ops.yaml         # the default view for operations engineers
└── README.md
```

- **PACK-02** Column specs list column names, order, mandatory flag and type only. They
  are written from the public SCOS-2000 Database Import ICD; no ICD text is copied.

## 2. Sources

| Source id | What | Format | Extractor | Kind |
|---|---|---|---|---|
| `srdb` | Satellite reference database (SCOS-2000 MIB) | ASCII `.dat`, tab-separated, no header | `delimited` | record |
| `icd` | SW ICD | One HTML page with tables | `html` | text |
| `sum` | SW user manual | `.docx` and/or PDF | `docx`, `pdf` | text |
| `code` | SCSW code | C `.c` / `.h` | `c` | text (+ `Function` entities) |
| `fops` | Flight operations procedures | Python scripts | `python` | text |

- **PACK-03** `srdb` options: `icd_issue` (selects `srdb/icd/<issue>.yaml`),
  `custom_columns` (per table, appended after the mandatory ones, e.g. `pcf: [PCF_LDESCR]`),
  `encoding` (default `utf-8`, fallback `latin-1` with a warning).
- **PACK-04** `sum` accepts several files. If a document is given as both `.docx` and PDF
  (same stem), `.docx` is used and the PDF is ignored with an info diagnostic (Q2).

## 3. SRDB entity types

Class names are the table names, so nothing is renamed; views give them human labels.
Key columns and relations below are to be checked against the chosen ICD issue in
milestone M2.

| Class | Table | Key | Relations (slot → class) | Surface forms | Label in ops view |
|---|---|---|---|---|---|
| `PCF` | Parameters | `PCF_NAME` | `PCF_CURTX` → `CAF`/`TXF`/`MCF`/`LGF` by `PCF_CATEG` (`range_by`) | `PCF_NAME`, `PCF_DESCR` | Parameter |
| `CAF` / `CAP` | Numerical calibration / points | `CAF_NUMBR` / (`CAP_NUMBR`, `CAP_XVALS`) | `CAP_NUMBR` → `CAF` | — | Calibration |
| `TXF` / `TXP` | Textual calibration / values | `TXF_NUMBR` / (`TXP_NUMBR`, `TXP_FROM`) | `TXP_NUMBR` → `TXF` | `TXP_ALTXT` (off by default) | Text calibration |
| `MCF`, `LGF` | Polynomial / logarithmic calibration | ident | — | — | Calibration |
| `CUR` | Calibration selection | (`CUR_PNAME`, `CUR_POS`) | `CUR_PNAME` → `PCF`, `CUR_RLCHK` → `PCF` | — | Calibration selection |
| `PID` | Packet identification | `PID_SPID` | — | — | Packet |
| `PIC` | Packet identification criteria | per ICD issue | — | — | Packet criteria |
| `TPCF` | Packet names | `TPCF_SPID` | `TPCF_SPID` → `PID` | `TPCF_NAME` (resolves to the packet) | Packet name |
| `PLF` | Parameters in packets | (`PLF_NAME`, `PLF_SPID`, `PLF_OFFBY`, `PLF_OFFBI`) | `PLF_NAME` → `PCF`, `PLF_SPID` → `PID` | — | Packet field |
| `OCF` / `OCP` | Monitoring checks / limits | `OCF_NAME` / (`OCP_NAME`, `OCP_POS`) | `OCF_NAME` → `PCF`, `OCP_NAME` → `OCF` | — | Limit check |
| `CCF` | Commands | `CCF_CNAME` | — | `CCF_CNAME`, `CCF_DESCR` | Telecommand |
| `CPC` | Command parameters | `CPC_PNAME` | — | `CPC_PNAME` | TC argument |
| `CDF` | Command elements | (`CDF_CNAME`, `CDF_BIT`) | `CDF_CNAME` → `CCF`, `CDF_PNAME` → `CPC` | — | TC element |
| `VDF` | Database version | `VDF_NAME` | — | — | Database version |

ID patterns (`mosaic.id_pattern`, used to spot unresolved references) are project
overridable; defaults match the mock mission: `PCF` `\b[A-Z]{3}T\d{4}\b`, `CCF`
`\b[A-Z]{3}C\d{4}\b`.

- **PACK-05** A table file that is absent is skipped with an info diagnostic; relations
  into it are not reported as broken.
- **PACK-06** Custom columns become ordinary attributes; a custom column named in
  `custom_columns` with `mosaic.text_slot` is searchable (e.g. the long description).

### 3.1 Code entities

| Class | Key | From | Relations |
|---|---|---|---|
| `Function` | `<file path>::<name>` | Each C function definition | `handles` → `CCF` (promoted, rule `function-handles-tc`) |

## 4. Link rules

Roles used by this pack: `describes`, `defines_id`, `handles`, `uses`, `sends`, `sets`,
`reads`, `mentions`.

| Rule id | Source | Where | Target (match on) | Role | Prio |
|---|---|---|---|---|---|
| `fop-sends-tc` | fops | `call_arg{func: send_tc, arg: 0}` | CCF (`CCF_CNAME`) | sends | 20 |
| `fop-sets-arg` | fops | `call_kw{func: send_tc}` | CPC (`CPC_PNAME`) | sets | 20 |
| `fop-reads-tm` | fops | `call_arg{func: [verify_tm, get_tm], arg: 0}` | PCF (`PCF_NAME`) | reads | 20 |
| `code-define-param` | code | `define_name`, extract `^PARAM_(?P<ref>\w+)$` | PCF (`PCF_NAME`) | defines_id | 20 |
| `code-enum-tc` | code | `enum_constant`, extract `^TC_(?P<ref>\w+)$` | CCF (`CCF_CNAME`) | defines_id | 20 |
| `code-handles-tc` | code | `case_label` inside a function, extract `^TC_(?P<ref>\w+)$` | CCF (`CCF_CNAME`) | handles | 30 |
| `code-uses-id` | code | `identifier`, extract `^(PARAM\|TC)_(?P<ref>\w+)$` | PCF, CCF (IDs) | uses | 10 |
| `doc-describes` | sum, icd | `heading`, or `table_cell` whose column header is one of *TC, Parameter, Argument, Mnemonic, Name, ID* | PCF, CCF, CPC, PID (all forms) | describes | 10 |
| `text-mentions` | all | `paragraph`, `list_item`, `table_cell`, `comment`, `docstring`, `heading`, `caption` | PCF, CCF, CPC, PID (all forms) | mentions | 0 |

Function names, header lists and the `PARAM_`/`TC_` prefixes are pack defaults matching
the mock; real conventions are project overrides once Q4 and Q5 are answered.

- **PACK-10** Within one FOP call such as `send_tc("PWRC0101", PWRP0001=1)`, the TC mention
  and its argument mentions share the step scope, so the detail panel can show "sent by
  step 2 of FOP-PWR-001 with `PWRP0001=1`".

## 5. Relation and cross-reference rules

| Rule id | Shape | From → To | Type |
|---|---|---|---|
| `function-handles-tc` | promote | enclosing `Function` → mentioned CCF, from role `handles` | `handles` |
| `fop-step-described-in-manual` | via entity | FOP step (`sends`, `reads`) → SUM section (`describes`) | `described_in` |
| `fop-step-defined-in-icd` | via entity | FOP step (`sends`, `reads`) → ICD section (`describes`) | `defined_in` |
| `fop-step-handled-by-code` | via entity | FOP step (`sends`) → C function scope (`handles`) | `handled_by` |
| `code-file-documented-in` | explicit map, fallback via entity (min 2 shared, `handles`/`defines_id` → `describes`) | C file → SUM section | `documented_in` |
| `manual-section-to-icd` | via entity | SUM section (`describes`) → ICD section (`describes`) | `see_also` |

## 6. The default view: `ops`

The only view shipped (D8). Full schema in `03-viewer.md`.

```yaml
id: ops
title: Operations
audience: Operations engineers
layout: {navigator: true, main: reader, side: detail}
landing: {source: fops}
navigator:
  - {title: Procedures, sources: [fops]}
  - {title: SW user manual, sources: [sum]}
  - {title: SW ICD, sources: [icd]}
  - {title: SRDB, tables: [PCF, CCF, CPC, PID, CAF, TXF, OCF]}
  - {title: SCSW code, sources: [code]}
types:
  PCF: {label: Parameter, title: PCF_NAME, subtitle: PCF_DESCR, columns: [PCF_NAME, PCF_DESCR, PCF_UNIT, PCF_PTC, PCF_PFC, PCF_LDESCR]}
  CCF: {label: Telecommand, title: CCF_CNAME, subtitle: CCF_DESCR, columns: [CCF_CNAME, CCF_DESCR, CCF_TYPE, CCF_STYPE, CCF_APID]}
detail:
  CCF:
    - {title: Definition, show: attributes}
    - {title: Arguments, show: relations, path: "CDF.CDF_CNAME<- / CDF_PNAME->"}
    - {title: Handled by, show: relations, type: handles, direction: in}
    - {title: Described in, show: mentions, roles: [describes]}
    - {title: Sent by, show: mentions, roles: [sends], group_by: scope}
    - {title: Other mentions, show: mentions, roles: [mentions, defines_id, uses]}
  PCF:
    - {title: Definition, show: attributes}
    - {title: Calibration, show: relations, path: "PCF_CURTX->"}
    - {title: In packets, show: relations, path: "PLF.PLF_NAME<- / PLF_SPID->"}
    - {title: Limit checks, show: relations, path: "OCF.OCF_NAME<-"}
    - {title: Described in, show: mentions, roles: [describes]}
    - {title: Read by, show: mentions, roles: [reads], group_by: scope}
    - {title: Other mentions, show: mentions, roles: [mentions, defines_id, uses]}
export:
  sources: all
  types: all
  diagnostics: true
```

## 7. Acceptance criteria against the demo mission

Measured by the e2e test that builds the mocker's output and compares the store with
`ground_truth.json` (see `04-mocker.md`).

- **PACK-20** Clean small mission: every ground-truth mention marked `exact` is found with
  the right entity and role (recall 1.0) and no mention is found that is not in the ground
  truth (precision 1.0).
- **PACK-21** Every ground-truth cross-reference of the types in § 5 is present.
- **PACK-22** Mission with the default defect set: every defect whose
  `expected_detection` starts with `v1:` raises that diagnostic at the recorded location;
  defects marked `future` raise nothing, and no other warning or error is raised.
- **PACK-23** Building the mission once with the manual's `.docx` and once with its PDF
  gives the same section titles and the same mention set, apart from page tags.
- **PACK-24** Building the small mission takes under 10 s (CORE-95).
