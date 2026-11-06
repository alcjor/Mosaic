"""Edge cases of the Netflix fixture flow (Specification 0.1; plan M1.2), from the spec's words.

Written by the verifier without reading the implementation. Like ``test_netflix.py`` these are
``slow``: they import the pinned source (downloaded by ``scripts/fetch_fixtures.py``) and build
the pattern in ``conformance/fixtures/netflix/``. One import and one build are shared; the tests
that need a changed pattern or environment run their own, short where they can.

Sections: 3.2 (sources), 3.5 (evidence and locators), 3.6 (hashes), 3.8 (reading rules),
4.3 (determinism), 5.1 (pins), 5.4 (budget, strict), 7.1 and 7.2 (build and report), 7.3.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from mosaic_format.reader import Limits, SealedFile
from mosaic_format.reader import open as open_sealed

from tests.conftest import REPO, SPEC
from tests.test_cli import entry_point

FIXTURE = REPO / "conformance" / "fixtures" / "netflix"
SOURCE = REPO / "conformance" / "fixtures" / "downloads" / "netflix-titles" / "netflix_titles.csv"
MANIFEST = REPO / "conformance" / "fixtures" / "manifest.json"
ALL_ROWS = Limits(seconds=None, rows=None)

# Section 5.2: the Unicode White_Space set, which is not Python's str.strip() set.
WHITE_SPACE = "".join(
    chr(c)
    for c in (
        *range(0x09, 0x0E),
        0x20,
        0x85,
        0xA0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
    )
)

pytestmark = pytest.mark.slow


def _run(
    *args: str | Path, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(entry_point()), *(str(a) for a in args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def _ok(*args: str | Path, cwd: Path, env: dict[str, str] | None = None) -> str:
    done = _run(*args, cwd=cwd, env=env)
    assert done.returncode == 0, f"mosaic {args[0]} failed:\n{done.stdout}{done.stderr}"
    return done.stdout


def _query(
    sealed: SealedFile,
    sql: str,
    params: list[object] | None = None,
    *,
    limits: Limits | None = None,
) -> list[tuple[Any, ...]]:
    return sealed.query(sql, params or (), limits=limits)  # type: ignore[return-value]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _knowledge_hash(path: Path) -> str:
    with open_sealed(path) as sealed:
        return sealed.knowledge_hash


def _pin() -> tuple[str, str]:
    text = (FIXTURE / "pattern.yaml").read_text(encoding="utf-8")
    found = re.search(r"^\s*-\s*([A-Za-z0-9_-]+)@([0-9a-f]{64})\s*$", text, re.MULTILINE)
    assert found, "pattern.yaml pins no piece as name@hash"
    return found.group(1), found.group(2)


def _pattern_with(directory: Path, *, pin: str | None = None, mosaics: str = "") -> Path:
    name, pinned = _pin()
    text = (FIXTURE / "pattern.yaml").read_text(encoding="utf-8")
    text = text.replace(f"{name}@{pinned}", f"{name}@{pin or pinned}")
    path = directory / "pattern.yaml"
    path.write_text(text + mosaics, encoding="utf-8")
    return path


@dataclass(frozen=True)
class Flow:
    directory: Path
    pieces: Path
    out: Path
    tessera: Path
    mosaic: Path
    tessera_hash: str
    mosaic_hash: str
    report: dict[str, object]


@pytest.fixture(scope="module")
def fetched() -> None:
    done = subprocess.run(
        [sys.executable, "-I", str(REPO / "scripts" / "fetch_fixtures.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert "ok   netflix-titles" in done.stdout, done.stdout + done.stderr


@pytest.fixture(scope="module")
def flow(fetched: None, tmp_path_factory: pytest.TempPathFactory) -> Flow:
    directory = tmp_path_factory.mktemp("netflix-edges")
    name, _ = _pin()
    pieces, out = directory / "pieces", directory / "out"
    pieces.mkdir()
    tessera = pieces / f"{name}.tessera"
    shutil.copyfile(SOURCE, directory / SOURCE.name)
    _ok(
        "import", "csv", SOURCE.name, "--settings", FIXTURE / "settings.yaml", "-o", tessera,
        cwd=directory,
    )  # fmt: skip
    _ok("build", FIXTURE / "pattern.yaml", "--pieces", pieces, "-o", out, cwd=directory)
    mosaic = out / "default.mosaic"
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    return Flow(
        directory, pieces, out, tessera, mosaic, _knowledge_hash(tessera),
        _knowledge_hash(mosaic), report,
    )  # fmt: skip


def _trim(text: str) -> str:
    return text.strip(WHITE_SPACE)


def _rows() -> list[dict[str, str]]:
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _values(cell: str, separator: str | None) -> list[str]:
    parts = cell.split(separator) if separator else [cell]
    return [v for v in (_trim(p) for p in parts) if v]


def _schema() -> Validator:
    return Draft202012Validator(
        json.loads((SPEC / "build-report.schema.json").read_text(encoding="utf-8"))
    )


# --- The source is only read (principle 8) and is the pinned one (section 3.2) ---


def test_import_and_build_leave_the_source_bytes_unchanged(flow: Flow) -> None:
    # Principle 8: never write to a source.
    pinned = next(
        f for f in json.loads(MANIFEST.read_text())["fixtures"] if f["name"] == "netflix-titles"
    )
    assert _sha256(SOURCE) == pinned["sha256"]
    assert _sha256(flow.directory / SOURCE.name) == pinned["sha256"]


def test_the_mosaic_names_the_pinned_tessera_and_csv_as_sources(flow: Flow) -> None:
    # Section 3.2: one row per piece; the piece's original sources are copied, id prefixed.
    pinned_csv = next(
        f for f in json.loads(MANIFEST.read_text())["fixtures"] if f["name"] == "netflix-titles"
    )["sha256"]
    name, pin = _pin()
    with open_sealed(flow.mosaic) as mosaic:
        rows = _query(mosaic, "SELECT id, kind, hash FROM source ORDER BY id", limits=ALL_ROWS)
    assert (name, "tessera", pin) in rows
    files = [r for r in rows if r[1] == "file"]
    assert len(files) == 1
    assert files[0][0].startswith(f"{name}/")
    assert files[0][2] == pinned_csv


# --- The pin (section 5.1, 7.1 step 1, 7.2, 7.3) ---


def test_a_pin_that_matches_no_piece_fails_the_build_with_a_valid_report(
    flow: Flow, tmp_path: Path
) -> None:
    # Section 5.1: a piece that matches no available file is a violation; 7.3: failed report shape.
    _, pinned = _pin()
    wrong = pinned[:-1] + ("0" if pinned[-1] != "0" else "1")
    pattern = _pattern_with(tmp_path, pin=wrong)
    out = tmp_path / "out"
    done = _run("build", pattern, "--pieces", flow.pieces, "-o", out, cwd=tmp_path)
    assert done.returncode != 0
    assert not list(out.glob("*.mosaic"))
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    _schema().validate(report)
    assert report["outcome"] == "failed"
    assert report["reason"] == "piece_mismatch"
    assert report["pattern_hash"] == _sha256(pattern)
    assert report["knowledge_hash"] is None
    assert report["vector_hash"] is None
    assert report["file_size"] is None
    assert report["counts"] == {"nodes": {}, "edges": {}}


def test_check_of_a_pattern_with_a_wrong_pin_fails(flow: Flow, tmp_path: Path) -> None:
    # Section 5.1 with `mosaic check` of a pattern.
    _, pinned = _pin()
    wrong = ("0" if pinned[0] != "0" else "1") + pinned[1:]
    pattern = _pattern_with(tmp_path, pin=wrong)
    done = _run("check", pattern, "--pieces", flow.pieces, cwd=tmp_path)
    assert done.returncode != 0
    assert "Traceback" not in done.stdout + done.stderr


def test_a_pin_of_seven_characters_is_refused(flow: Flow, tmp_path: Path) -> None:
    # Section 5.1: a prefix of at least 8 characters MAY be given.
    _, pinned = _pin()
    pattern = _pattern_with(tmp_path, pin=pinned[:7])
    out = tmp_path / "out"
    done = _run("build", pattern, "--pieces", flow.pieces, "-o", out, cwd=tmp_path)
    assert done.returncode != 0
    assert not list(out.glob("*.mosaic"))


def test_a_pin_of_eight_characters_builds_the_same_mosaic(flow: Flow, tmp_path: Path) -> None:
    # Section 5.1: a prefix of at least 8 characters that matches one file resolves it.
    _, pinned = _pin()
    pattern = _pattern_with(tmp_path, pin=pinned[:8])
    out = tmp_path / "out"
    _ok("build", pattern, "--pieces", flow.pieces, "-o", out, cwd=tmp_path)
    assert _knowledge_hash(out / "default.mosaic") == flow.mosaic_hash


def test_two_files_with_one_prefix_do_not_crash_the_build(flow: Flow, tmp_path: Path) -> None:
    # Section 5.1: a prefix MUST match exactly one available file.
    name, pinned = _pin()
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    shutil.copyfile(flow.tessera, pieces / f"{name}.tessera")
    shutil.copyfile(flow.tessera, pieces / f"{name}-copy.tessera")
    pattern = _pattern_with(tmp_path, pin=pinned[:8])
    done = _run("build", pattern, "--pieces", pieces, "-o", tmp_path / "out", cwd=tmp_path)
    # Two files with the same hash are one piece or two matches; the build must not crash.
    assert "Traceback" not in done.stdout + done.stderr


# --- The tessera against the CSV, counted independently (sections 4.1, 5.2, 5.3, 7.2) ---


LINKS = {
    # column -> (separator, node type in the mosaic, edge type)
    "director": (",", "Person", "directed_by"),
    "cast": (",", "Person", "features"),
    "country": (",", "Country", "made_in"),
    "listed_in": (",", "Genre", "listed_in"),
    "release_year": (None, "Year", "released_in"),
}


def test_node_counts_equal_the_distinct_trimmed_values_of_the_csv(flow: Flow) -> None:
    # Sections 4.1 and 5.2: one node per distinct trimmed value; empty values make none; the
    # Person type is the union of directors and cast.
    rows = _rows()
    wanted: dict[str, set[str]] = {"Title": {r["show_id"] for r in rows}}
    for column, (separator, node_type, _) in LINKS.items():
        found = wanted.setdefault(node_type, set())
        for row in rows:
            found.update(_values(row[column], separator))
    counts = flow.report["counts"]
    assert isinstance(counts, dict)
    assert {t: n for t, n in counts["nodes"].items()} == {t: len(v) for t, v in wanted.items()}


def test_edge_counts_equal_the_distinct_row_and_value_pairs_of_the_csv(flow: Flow) -> None:
    # Section 4.1 (one edge per row and value pair) and 7.1 step 5 (duplicates are one edge).
    rows = _rows()
    wanted: dict[str, set[tuple[str, str]]] = {}
    for column, (separator, _, edge_type) in LINKS.items():
        pairs = wanted.setdefault(edge_type, set())
        for row in rows:
            pairs.update((row["show_id"], v) for v in _values(row[column], separator))
    counts = flow.report["counts"]
    assert isinstance(counts, dict)
    assert counts["edges"] == {t: len(p) for t, p in wanted.items()}


def test_a_person_who_directs_and_acts_is_one_node_with_both_edges(flow: Flow) -> None:
    # Sections 5.2 and 7.1 step 3: nodes of the same type and key are one node.
    rows = _rows()
    directors = {v for r in rows for v in _values(r["director"], ",")}
    cast = {v for r in rows for v in _values(r["cast"], ",")}
    both = sorted(directors & cast)
    assert both, "the source has no person who directs and acts"
    sample = both[0]
    with open_sealed(flow.mosaic) as mosaic:
        nodes = _query(mosaic, "SELECT nid FROM node WHERE id = ?", [f"Person:{sample}"])
        assert len(nodes) == 1
        kinds = {
            r[0]
            for r in _query(
                mosaic,
                "SELECT DISTINCT type FROM edge WHERE dst = ?",
                [nodes[0][0]],
                limits=ALL_ROWS,
            )
        }
    assert kinds == {"directed_by", "features"}


def test_no_key_has_white_space_at_its_ends(flow: Flow) -> None:
    # Sections 4.1 (each value is trimmed) and 5.2 (default normalisation is trim).
    with open_sealed(flow.mosaic) as mosaic:
        keys = _query(mosaic, "SELECT id, key FROM node", limits=ALL_ROWS)
    bad = [k for k in keys if k[1] == "" or k[1][0] in WHITE_SPACE or k[1][-1] in WHITE_SPACE]
    assert bad == []


def test_a_title_without_a_director_has_no_directed_by_edge(flow: Flow) -> None:
    # Section 4.1: an empty cell makes no node and no edge.
    rows = _rows()
    empty = next(r["show_id"] for r in rows if _trim(r["director"]) == "")
    with open_sealed(flow.mosaic) as mosaic:
        found = _query(
            mosaic,
            "SELECT count(*) FROM edge e JOIN node n ON n.nid = e.src "
            "WHERE n.id = ? AND e.type = 'directed_by'",
            [f"Title:{empty}"],
        )
        assert _query(mosaic, "SELECT 1 FROM node WHERE id = ?", [f"Title:{empty}"])
    assert found == [(0,)]


def test_dates_become_dates_and_durations_quantities(flow: Flow) -> None:
    # Section 4.1 conversions chosen in settings.yaml: date_added a date, duration a quantity.
    with open_sealed(flow.mosaic) as mosaic:
        rows = _query(mosaic, "SELECT id, props FROM node WHERE type = 'Title'", limits=ALL_ROWS)
    props = {i: json.loads(p) for i, p in rows}
    source = {f"Title:{r['show_id']}": r for r in _rows()}
    assert len(props) == len(source)
    dated = 0
    for node_id, p in props.items():
        added = _trim(source[node_id]["date_added"])
        if not added:
            assert "date_added" not in p, node_id
            continue
        dated += 1
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["date_added"]), (node_id, p["date_added"])
    assert dated > 8000
    # `duration` is a number when the cell holds a number and a unit.
    by_unit = {p.get("duration_unit") for p in props.values()}
    assert by_unit <= {None, "minute", "season"}
    assert {"minute", "season"} <= by_unit
    first = props["Title:s1"]
    assert (first["duration"], first["duration_unit"]) == (90, "minute")
    assert (props["Title:s2"]["duration"], props["Title:s2"]["duration_unit"]) == (2, "season")
    # A "1 Season" cell and a "2 Seasons" cell are the same unit.
    assert (props["Title:s3"]["duration"], props["Title:s3"]["duration_unit"]) == (1, "season")


def test_rows_with_a_misplaced_duration_still_become_titles(flow: Flow) -> None:
    # Section 4.1: a cell that cannot be converted must not lose the row. In the source a few
    # titles hold their duration in `rating` and leave `duration` empty.
    rows = [r for r in _rows() if _trim(r["duration"]) == ""]
    assert rows, "the source has no empty duration"
    with open_sealed(flow.mosaic) as mosaic:
        for row in rows:
            found = _query(
                mosaic, "SELECT props FROM node WHERE id = ?", [f"Title:{row['show_id']}"]
            )
            assert len(found) == 1, row["show_id"]
            assert "duration" not in json.loads(found[0][0])


# --- Evidence on every node and edge (principle 4; sections 3.5, 3.9 invariant on evidence) ---


def test_every_node_and_every_edge_has_evidence_with_a_locator(flow: Flow) -> None:
    with open_sealed(flow.mosaic) as mosaic:
        bare_nodes = _query(
            mosaic,
            "SELECT count(*) FROM node n "
            "WHERE NOT EXISTS (SELECT 1 FROM evidence v WHERE v.nid = n.nid)",
        )
        bare_edges = _query(
            mosaic,
            "SELECT count(*) FROM edge e "
            "WHERE NOT EXISTS (SELECT 1 FROM evidence v WHERE v.eid = e.eid)",
        )
        empty = _query(mosaic, "SELECT count(*) FROM evidence WHERE locator = ''")
    assert bare_nodes == [(0,)]
    assert bare_edges == [(0,)]
    assert empty == [(0,)]


def test_an_edges_locator_points_at_its_titles_row_and_the_edges_column(flow: Flow) -> None:
    # Section 3.5: a locator is `name=value` pairs; the row is the title's own row, the field the
    # column the value came from.
    column_of = {edge: column for column, (_, _, edge) in LINKS.items()}
    with open_sealed(flow.mosaic) as mosaic:
        title_rows = {
            nid: dict(p.split("=", 1) for p in loc.split(";"))
            for nid, loc in _query(
                mosaic,
                "SELECT n.nid, v.locator FROM node n JOIN evidence v ON v.nid = n.nid "
                "WHERE n.type = 'Title' AND v.prop IS NULL",
                limits=ALL_ROWS,
            )
        }
        edges = _query(
            mosaic,
            "SELECT e.type, e.src, v.locator FROM edge e JOIN evidence v ON v.eid = e.eid",
            limits=ALL_ROWS,
        )
    assert len(title_rows) == 8807
    assert len(edges) > 8807
    for edge_type, src, locator in edges:
        pairs = dict(p.split("=", 1) for p in locator.split(";"))
        assert pairs["field"] == column_of[edge_type], locator
        assert pairs["row"] == title_rows[src]["row"], locator
        assert pairs["file"] == title_rows[src]["file"], locator


# --- The report (section 7.2) ---


def test_a_single_piece_build_reports_no_conflicts_or_stale_references(flow: Flow) -> None:
    # Section 7.2: one piece has no losers; there are no mention rules.
    report = flow.report
    for entry in ("conflicts", "alias_conflicts", "stale_references", "mentions", "proposals"):
        assert report[entry] == [], entry
    name, _ = _pin()
    notices = report["notices"]
    assert isinstance(notices, list)
    assert all(n["piece"] == name for n in notices)


def test_the_report_names_the_target_default_and_hashes_the_pattern(flow: Flow) -> None:
    # Section 5.4: a pattern without targets has one, `default`; 7.2: pattern hash is the file's.
    assert flow.report["target"] == "default"
    assert flow.report["pattern_hash"] == _sha256(FIXTURE / "pattern.yaml")
    assert flow.report["format"] == "0.1"
    with open_sealed(flow.mosaic) as mosaic:
        assert flow.report["vector_hash"] == mosaic.vector_hash


def test_the_report_lists_every_declared_type_with_its_count(flow: Flow) -> None:
    # Section 7.2: counts per type, every declared type, 0 when it has no rows.
    counts = flow.report["counts"]
    assert isinstance(counts, dict)
    with open_sealed(flow.mosaic) as mosaic:
        declared = _query(mosaic, "SELECT name, kind FROM type", limits=ALL_ROWS)
        actual_nodes = dict(_query(mosaic, "SELECT type, count(*) FROM node GROUP BY type"))
        actual_edges = dict(_query(mosaic, "SELECT type, count(*) FROM edge GROUP BY type"))
    assert set(counts["nodes"]) == {n for n, k in declared if k == "node"}
    assert set(counts["edges"]) == {n for n, k in declared if k == "edge"}
    assert counts["nodes"] == actual_nodes
    assert counts["edges"] == actual_edges


# --- Targets: strict and budget (sections 5.4, 7.1 step 8, 7.3) ---


def test_a_strict_target_builds_the_same_knowledge_hash(flow: Flow, tmp_path: Path) -> None:
    # Sections 5.4 and 7.3: strict fails only on conflicts, alias conflicts and unmatched
    # mentions; the fixture has none, and the header (target, settings) is not hashed (3.6).
    pattern = _pattern_with(tmp_path, mosaics="\nmosaics:\n  tight: {strict: true}\n")
    out = tmp_path / "out"
    _ok("build", pattern, "--pieces", flow.pieces, "-o", out, cwd=tmp_path)
    assert _knowledge_hash(out / "tight.mosaic") == flow.mosaic_hash
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    _schema().validate(report)
    assert (report["outcome"], report["target"]) == ("built", "tight")


def test_a_target_the_pattern_does_not_define_fails(flow: Flow, tmp_path: Path) -> None:
    # Section 5.4: building a target the pattern does not define fails with invalid_input.
    out = tmp_path / "out"
    done = _run(
        "build", FIXTURE / "pattern.yaml", "--pieces", flow.pieces, "--target", "nope",
        "-o", out, cwd=tmp_path,
    )  # fmt: skip
    assert done.returncode != 0
    assert not list(out.glob("*.mosaic"))
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    _schema().validate(report)
    assert (report["outcome"], report["reason"]) == ("failed", "invalid_input")
    assert report["knowledge_hash"] is None


def test_a_budget_below_the_file_size_fails_and_leaves_no_mosaic(
    flow: Flow, tmp_path: Path
) -> None:
    # Sections 5.4 and 7.1 step 8: over budget fails, no mosaic is written; 7.3: the report gives
    # the removed file's hashes and size, with counts filled.
    pattern = _pattern_with(tmp_path, mosaics="\nmosaics:\n  small: {budget: 1 MB}\n")
    out = tmp_path / "out"
    done = _run("build", pattern, "--pieces", flow.pieces, "-o", out, cwd=tmp_path)
    assert done.returncode != 0
    assert not list(out.glob("*.mosaic"))
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    _schema().validate(report)
    assert (report["outcome"], report["reason"]) == ("failed", "over_budget")
    assert report["knowledge_hash"] == flow.mosaic_hash
    assert report["file_size"] == flow.report["file_size"]
    assert report["counts"] == flow.report["counts"]


def test_a_budget_of_the_exact_file_size_builds(flow: Flow, tmp_path: Path) -> None:
    # Section 5.4: the build fails when the mosaic is *larger* than the budget, in decimal units
    # compared with the size of the sealed file; equal is allowed.
    size = flow.report["file_size"]
    assert isinstance(size, int)
    pattern = _pattern_with(tmp_path, mosaics=f"\nmosaics:\n  exact: {{budget: {size} B}}\n")
    out = tmp_path / "out"
    done = _run("build", pattern, "--pieces", flow.pieces, "-o", out, cwd=tmp_path)
    if done.returncode != 0 and "invalid" in (done.stdout + done.stderr).lower():
        pytest.fail(f"a budget of '{size} B' is refused: {done.stdout}{done.stderr}")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (out / "exact.mosaic").stat().st_size == size


# --- Repeated builds (section 4.3, principle 5) ---


def test_the_mosaic_does_not_depend_on_where_or_how_the_command_runs(
    flow: Flow, tmp_path: Path
) -> None:
    # Section 7 / principle 5: the output directory and the working directory are not inputs.
    other = tmp_path / "elsewhere" / "deeper"
    other.mkdir(parents=True)
    out = other / "result"
    _ok("build", FIXTURE / "pattern.yaml", "--pieces", flow.pieces, "-o", out, cwd=other)
    assert (out / "default.mosaic").read_bytes() == flow.mosaic.read_bytes()


def test_the_tessera_hash_does_not_depend_on_environment(flow: Flow, tmp_path: Path) -> None:
    # Section 4.3: the same source and settings give the same knowledge hash, whatever the hash
    # seed, time zone, locale or working directory (CLAUDE.md: no dependence on locale or order).
    name, pinned = _pin()
    shutil.copyfile(SOURCE, tmp_path / SOURCE.name)
    env = dict(os.environ)
    env.update(PYTHONHASHSEED="12345", TZ="Pacific/Kiritimati", LC_ALL="C", LANG="C")
    env.pop("PYTHONUTF8", None)
    target = tmp_path / f"{name}.tessera"
    _ok(
        "import", "csv", tmp_path / SOURCE.name, "--settings", FIXTURE / "settings.yaml",
        "-o", target, cwd=Path("/"), env=env,
    )  # fmt: skip
    assert _knowledge_hash(target) == pinned


def test_check_of_the_tessera_and_of_the_mosaic_pass(flow: Flow) -> None:
    # `mosaic check` on the tessera and on the mosaic (with its pieces).
    out = _ok("check", flow.tessera, cwd=flow.directory)
    assert "ok" in out
    _ok("check", flow.mosaic, "--pieces", flow.pieces, cwd=flow.directory)


# --- Untrusted and corrupt files (section 3.8) ---


def test_a_mosaic_with_a_changed_byte_is_not_accepted(flow: Flow, tmp_path: Path) -> None:
    # Section 3.8: hashes are verified when a file is opened; a changed file is refused, with an
    # error, not a crash.
    data = bytearray(flow.mosaic.read_bytes())
    data[len(data) // 2] ^= 0xFF
    broken = tmp_path / "broken.mosaic"
    broken.write_bytes(bytes(data))
    done = _run("check", broken, "--pieces", flow.pieces, cwd=tmp_path)
    assert done.returncode != 0
    assert "Traceback" not in done.stdout + done.stderr


def test_a_truncated_mosaic_is_not_accepted(flow: Flow, tmp_path: Path) -> None:
    # Section 3.8: an untrusted file that is cut short is refused with an error, not a crash.
    broken = tmp_path / "cut.mosaic"
    broken.write_bytes(flow.mosaic.read_bytes()[:100_000])
    done = _run("check", broken, cwd=tmp_path)
    assert done.returncode != 0
    assert "Traceback" not in done.stdout + done.stderr


def test_a_mosaic_is_not_accepted_as_a_pin_of_a_changed_tessera(flow: Flow, tmp_path: Path) -> None:
    # Section 5.1: the pin is the piece's knowledge hash. A tessera built with different settings
    # (here: no year links) has another hash and must not satisfy the pattern.
    name, _ = _pin()
    settings = (FIXTURE / "settings.yaml").read_text(encoding="utf-8")
    changed = settings.replace("  release_year: {type: Year, edge: released_in}\n", "")
    assert changed != settings
    (tmp_path / "settings.yaml").write_text(changed, encoding="utf-8")
    shutil.copyfile(SOURCE, tmp_path / SOURCE.name)
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    _ok(
        "import", "csv", SOURCE.name, "--settings", tmp_path / "settings.yaml",
        "-o", pieces / f"{name}.tessera", cwd=tmp_path,
    )  # fmt: skip
    assert _knowledge_hash(pieces / f"{name}.tessera") != _pin()[1]
    done = _run(
        "build", FIXTURE / "pattern.yaml", "--pieces", pieces, "-o", tmp_path / "out", cwd=tmp_path
    )
    assert done.returncode != 0
    assert not list((tmp_path / "out").glob("*.mosaic"))
    report = json.loads((tmp_path / "out" / "build-report.json").read_text(encoding="utf-8"))
    assert (report["outcome"], report["reason"]) == ("failed", "piece_mismatch")
