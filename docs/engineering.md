# Engineering guide

How the repo is structured, how quality is kept, and the order to build things in.
Specs say *what*; this file says *how we work*.

## 1. Repository layout

```
mosaic/
├── CLAUDE.md                     # rules for Claude Code (project rules + Karpathy guidelines)
├── README.md
├── pyproject.toml                # uv workspace root: members, dev tools, tool config
├── uv.lock                       # committed
├── .python-version               # 3.14
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── .claude/skills/karpathy-guidelines/   # vendored skill (SKILL.md + SOURCE.md)
├── .claude/skills/mosaic-design/        # loads the design rules for any UI work
├── docs/
│   ├── specs/00-overview.md … 04-mocker.md
│   ├── engineering.md            # this file
│   └── decisions.md              # decision log
├── packages/
│   ├── mosaic-core/              # schema, config, pipeline, matching, store, read API
│   ├── mosaic-extractors/        # delimited, html, docx, pdf, c, python
│   ├── mosaic-server/            # live server and static exporter
│   ├── mosaic-cli/               # `mosaic` command
│   └── mosaic-mock/              # `mosaic-mock` command, engine, profiles
├── queries/                      # named SQL shared by Python and the viewer (CORE-80)
├── packs/
│   ├── spacecraft/               # the connected user manual pack
│   └── _toy/                     # non-space pack for genericity tests
├── viewer/                       # Svelte + Vite + TypeScript
├── design/
│   ├── mosaic/                   # read-only copy of the MOSAIC design system (tokens, logos, guidelines)
│   └── viewer-guidelines.md      # how the design system applies to the viewer (DG-xx rules)
├── examples/demosat-1/           # committed small mock mission (MOCK-17)
├── prototype/index.html          # clickable sketch; throwaway
├── scripts/                      # check.py, trace.py: cross-platform helpers
└── tests/                        # cross-package: e2e, query parity, genericity
```

Each package: `packages/<name>/pyproject.toml`, `src/<module>/`, `tests/`. Build backend
`uv_build`. Module names are distinct top-level packages (`mosaic_core`, …), not namespace
packages, to keep tooling simple.

## 2. Package boundaries

```
mosaic_cli ──▶ mosaic_server ──▶ mosaic_core
     └───────▶ mosaic_extractors ─┘
mosaic_mock  (imports none of the above)
viewer       (reads the store through queries/; imports no Python)
```

Enforced by import-linter in CI:

| Contract | Rule |
|---|---|
| layers | `mosaic_cli` › (`mosaic_server` \| `mosaic_extractors`) › `mosaic_core` |
| independence | `mosaic_mock` is independent of every other package (MOCK-01) |
| forbidden | `mosaic_core` imports no third-party document/code parser (those live in extractors) |

Domain-word lints (CORE-01, VIEW-03) run as tests.

## 3. Toolchain

| Concern | Tool | Notes |
|---|---|---|
| Environments, lock, run | uv | `uv sync --all-packages`; `uv run …` everywhere |
| Lint and format | ruff | `ruff check`, `ruff format`; rules below |
| Types | ty | Beta (0.0.x as of Oct 2026): pin the exact version; `# ty: ignore[rule]` needs a reason comment |
| Tests | pytest, pytest-cov, hypothesis, syrupy | Markers below |
| Boundaries | import-linter | Contracts in root `pyproject.toml` |
| Hooks | pre-commit | ruff, ruff-format, end-of-file, large files, `uv lock --check` |
| Viewer | npm, Vite, svelte-check, ESLint, Prettier, Vitest, Playwright | Node LTS, `package-lock.json` committed |
| Licences | pip-licenses, license-checker (npm) | Fail on GPL/AGPL (D14) |

Root `pyproject.toml` (sketch):

```toml
[project]
name = "mosaic-workspace"
version = "0.1.0"
requires-python = ">=3.14"

[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = ["ruff", "ty==<pinned>", "pytest", "pytest-cov", "hypothesis", "syrupy",
       "import-linter", "pre-commit", "pip-licenses"]

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF", "PT", "PTH", "N", "C4", "PL", "TID"]
ignore = ["PLR0913"]

[tool.pytest.ini_options]
addopts = "-ra --strict-markers"
markers = ["req(id): requirement covered", "e2e: end-to-end", "slow: > 1 s"]

[tool.importlinter]
root_packages = ["mosaic_core", "mosaic_extractors", "mosaic_server", "mosaic_cli", "mosaic_mock"]
```

One entry point runs every gate the same way locally and in CI:

```
uv run scripts/check.py            # all gates, fast ones first
uv run scripts/check.py --fast     # lint, types, unit tests
```

## 4. Quality gates (block merge)

1. `ruff check` and `ruff format --check`
2. `ty check`
3. import-linter
4. Unit and contract tests; branch coverage ≥ 90 % for `mosaic_core`, ≥ 80 % elsewhere
5. Generated files up to date: LinkML Pydantic models, query types, `examples/demosat-1`
6. Domain-word lints
7. Licence check
8. Viewer: `svelte-check`, ESLint, Prettier, Vitest; no colour literals outside the
   generated theme (DG-01); PRs touching the UI include light and dark screenshots
   (`design/viewer-guidelines.md` § 7)
9. e2e (§ 5): demo mission scoring and Playwright in both modes

## 5. Testing strategy

| Layer | What | Where | Budget |
|---|---|---|---|
| Unit | Pure functions: parsing, matching, offsets, path syntax | `packages/*/tests` | whole suite < 30 s |
| Contract | Every extractor against the shared contract (CORE-35); every named query in Python and WASM (CORE-80) | `tests/contract` | < 1 min |
| Integration | Full pipeline on the toy pack (CORE-06) | `tests/integration` | < 1 min |
| e2e | Mock → build → score against ground truth (PACK-20…24); viewer scenario (VIEW-81) | `tests/e2e` | < 5 min |

- **Ground-truth scoring is the headline test.** It prints precision and recall per role,
  defects detected, and timings, and uploads them as a CI artifact so trends are visible.
- **Property-based tests** (Hypothesis) for the delimited parser, offset conversion,
  overlap resolution and view merging.
- **Snapshots** (syrupy) for build reports and segment trees of fixtures. Snapshot diffs
  are reviewed in the PR; never update them blindly.
- **Fixtures**: tiny hand-written files per extractor in `tests/fixtures/`; anything larger
  comes from the mocker.
- **Traceability**: tests carry `@pytest.mark.req("CORE-41")`. `scripts/trace.py` lists
  requirement IDs in the specs with no test. It warns until M7 and fails after.

## 6. Specs, decisions, changes

- **Spec first.** A behaviour change updates the spec in the same PR. If the spec is
  wrong or unclear, fix the spec before the code.
- **Decision log** (`docs/decisions.md`): date, decision, why, alternatives considered.
  Spike outcomes go there too.
- **Small PRs**: aim for < 400 changed lines excluding generated files; squash merge;
  Conventional Commits (`feat(core): …`, `fix(viewer): …`).
- **Definition of done**: requirement tests pass and are tagged; all gates green; spec and
  `CHANGELOG.md` updated; `uv run mosaic demo` still works.
- **Versioning**: one SemVer 0.x version for the workspace; `store_version` versioned
  separately (CORE-73).

## 7. Working with Claude Code

### 7.1 The loop, one milestone at a time

1. **Issue.** One GitHub issue per milestone (M0…M7) inside a GitHub milestone, listing
   its exit criteria and requirement IDs. Split large ones (M3: one issue per extractor).
2. **Fresh session, plan first.** A new Claude Code session on its own branch (or
   worktree), started in plan mode with the kick-off prompt (§ 7.3). Read the plan and
   correct it before any code is written.
3. **Build.** Tests first, small commits, `uv run scripts/check.py` green. On spec
   ambiguity the agent stops and asks; spec edits are proposed, not made.
4. **Pull request.** Requirement IDs covered, the e2e scoring output, UI screenshots,
   open questions. CI green.
5. **Review.** `/code-review` while iterating; `/code-review ultra` (ultrareview, a
   deeper cloud review that reproduces each finding; a few free runs, then usage
   credits) on each milestone PR before merge. You read the summary and run the demo.
6. **Merge and record.** Squash-merge, close the issue, log decisions and spike results
   in `docs/decisions.md`, start the next milestone in a new session.

### 7.2 What the agent may change

| | Paths |
|---|---|
| Freely | Code and tests of the milestone's packages |
| Only after asking | `docs/specs/`, `queries/`, the store schema, dependencies, CI config |
| Never | `design/mosaic/`, `.claude/skills/karpathy-guidelines/`, generated files by hand |

A `PreToolUse` hook can enforce the last row (Claude Code hooks guide, "Block edits to
protected files").

### 7.3 Kick-off prompt

```
Milestone M3 (issue #12). Read CLAUDE.md, docs/specs/00-overview.md, 01-core.md §4–6,
02-spacecraft-pack.md §4–5 and docs/engineering.md. In plan mode:
1. List the requirement IDs this milestone covers and the test for each.
2. Propose the files and the order of work, each step with a verify command.
3. List anything ambiguous or contradictory in the spec.
Do not write code until I approve the plan.
```

### 7.4 Where ultracode fits

Ultracode (`/effort ultracode` for a session, or the `ultracode` keyword in one prompt)
has Claude write a workflow that runs many subagents in the background. Use it for wide,
checkable tasks, one stage per workflow:

- M0 spikes in parallel.
- "Audit every extractor against CORE-35 and adversarially verify each finding."
- "Review every file changed in this PR, then merge the findings into one ranked list."
- "Build the defect mission and keep fixing until PACK-22 passes or two rounds make no
  progress."

Not for building a milestone end to end: a workflow takes no input once running, so the
plan sign-off in § 7.1 is lost, and every task costs more tokens and reaches usage limits
sooner.

### 7.5 Tracking progress and quality

- **Progress:** the GitHub milestone board, plus `scripts/trace.py` (requirement IDs with
  and without tests).
- **Quality:** the CI scoring artifact per merged PR (precision and recall per role,
  defects detected, build time). A drop blocks the merge.
- **Independent oracle:** build the mocker (M1) before the core, and never change the
  mocker and the code it tests in the same PR.

## 8. CI (GitHub Actions)

```yaml
name: ci
on: [push, pull_request]
jobs:
  python:
    strategy: {matrix: {os: [ubuntu-latest, windows-latest]}}
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked --all-packages
      - run: uv run scripts/check.py --python
  viewer:
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: viewer}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: lts/*, cache: npm, cache-dependency-path: viewer/package-lock.json}
      - run: npm ci
      - run: npm run check && npm run lint && npm test
  e2e:
    needs: [python, viewer]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-node@v4
        with: {node-version: lts/*}
      - run: uv sync --locked --all-packages && (cd viewer && npm ci && npx playwright install --with-deps)
      - run: uv run pytest tests/e2e -m e2e
      - uses: actions/upload-artifact@v4
        with: {name: scoring, path: build/scoring.json}
```

The Windows leg exists because users may run Windows (Q7); drop it if they don't. Pin each
action to its current major version at M0 (the versions above are placeholders).

## 9. Dependencies

- Permissive licences only (MIT, BSD, Apache-2.0, PSF, ISC, MPL-2.0 file-level). No GPL or
  AGPL (for example, PyMuPDF is out), so the repo can be opened later.
- A new dependency needs a line in `decisions.md`: what it replaces, licence, maintenance.
- Planned: `linkml-runtime`, `pydantic` (core); `linkml` (dev, generation);
  `mammoth`, `lxml`, `pdfplumber`, `tree-sitter`, `tree-sitter-c` (extractors);
  `fastapi`, `uvicorn` (server); stdlib `argparse` (CLI); `jinja2`, `python-docx`,
  `reportlab` (mock).

## 10. Milestones

| | Goal | Exit criteria |
|---|---|---|
| **M0** | Skeleton and spikes | Workspace, CI green on empty packages, `CLAUDE.md`, `check.py`. Spikes recorded in `decisions.md`: **S1** LinkML generation and validation on Python 3.14; **S2** `@sqlite.org/sqlite-wasm` with FTS5 from `file://` (VIEW-50); **S3** ty on Protocols, dataclasses and Pydantic models; **S4** wheels for `tree-sitter`, `lxml`, `pdfplumber` on 3.14, Linux and Windows, and SQLite FTS5 in uv's Python on Windows (confirmed on Linux: Python 3.14.6, SQLite 3.53.1). A failed spike picks its fallback before M1 |
| **M1** | Mocker, clean | Spacecraft and toy profiles, small size, all artifacts, ground truth, `examples/demosat-1` committed; MOCK-01…17, 30…44 except defects |
| **M2** | Core and record sources | Core schema and models, config validation, `delimited`, schema relations, store writer, `t_` views, Python API, spacecraft schema and SRDB column specs; the demo SRDB builds |
| **M3** | Text sources and linking | `html`, `docx`, `pdf`, `c`, `python`; link rules; unresolved references; promoted relations; cross-references; PACK-20, 21, 23 |
| **M4** | Viewer, live | Server, named queries, shell, navigator, reader, table browser, detail panel, search, routing, theme; VIEW-81 in live mode |
| **M5** | Static export | WASM backend, export scope, `--single-file`; query parity; VIEW-50, VIEW-81 in static mode |
| **M6** | Defects and diagnostics | Defect injectors, diagnostics in reader and list; PACK-22 |
| **M7** | Hardening and demo | Large-size performance (CORE-95, VIEW-82), accessibility (VIEW-83), `mosaic demo`, README; traceability check fails on gaps |

## 11. Seeing everything fast

- Now: open `prototype/index.html` (also published as an artifact).
- After M1: `uv run mosaic-mock generate --profile spacecraft --out /tmp/demo` and browse
  the files; or just open `examples/demosat-1/`.
- After M4: `uv run mosaic demo` generates, builds, serves and opens the browser.
