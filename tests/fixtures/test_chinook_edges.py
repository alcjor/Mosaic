"""Edge cases of the Chinook fixture flow (Specification 0.1, section 11; plan M3.3).

Written by the verifier from the spec's words, without reading the implementation. Like
``test_chinook.py`` these are ``slow``: they import the pinned source (downloaded by
``scripts/fetch_fixtures.py``) and build ``conformance/fixtures/chinook/pattern.yaml``. One
import and one build with vectors are shared; the facts they find in the mosaic are compared with
the rows of the source database itself, read here with ``sqlite3``.

Sections: 3.4 (ids, keys, declared kinds), 3.5 (evidence), 3.6 (canonical order, hashes),
3.7 (vector hash), 3.9 (invariants), 4.3 (determinism), 5.1 (pins), 5.2 (keys), 5.3 (map),
7.1 and 7.2 (build and report), 8.1 (search).
"""

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mosaic_format.reader import Limits, SealedFile
from mosaic_format.reader import open as open_sealed
from mosaic_format.yaml_core import load

from tests.conftest import MODEL, REPO, SPEC
from tests.fixtures.expected import load_expected
from tests.test_cli import entry_point

FIXTURE = REPO / "conformance" / "fixtures" / "chinook"
SOURCE = REPO / "conformance" / "fixtures" / "downloads" / "chinook" / "Chinook_Sqlite.sqlite"
MANIFEST = REPO / "conformance" / "fixtures" / "manifest.json"
ALL_ROWS = Limits(seconds=None, rows=None)

pytestmark = pytest.mark.slow


def _mosaic(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(entry_point()), *(str(a) for a in args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _ok(*args: str | Path, cwd: Path) -> str:
    done = _mosaic(*args, cwd=cwd)
    assert done.returncode == 0, f"mosaic {args[0]} failed:\n{done.stdout}{done.stderr}"
    return done.stdout


def _pinned() -> tuple[str, str]:
    pattern = load((FIXTURE / "pattern.yaml").read_text(encoding="utf-8"), "pattern.yaml").data
    [piece] = pattern["pieces"]
    name, _, pinned = piece.partition("@")
    return name, pinned


def _source(sql: str) -> list[tuple[Any, ...]]:
    """Rows of the pinned database, read-only."""
    with sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True) as db:
        return db.execute(sql).fetchall()


def _import(directory: Path, pieces: Path, *, source: str | Path | None = None) -> Path:
    name, _ = _pinned()
    tessera = pieces / f"{name}.tessera"
    _ok(
        "import",
        "sqlite",
        source if source is not None else SOURCE.name,
        "--settings",
        FIXTURE / "settings.yaml",
        "-o",
        tessera,
        cwd=directory,
    )
    return tessera


@dataclass(frozen=True)
class Built:
    directory: Path
    pieces: Path
    tessera: Path
    mosaic: Path
    report: dict[str, object]

    def open(self) -> SealedFile:
        return open_sealed(self.mosaic, limits=ALL_ROWS)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    directory = tmp_path_factory.mktemp("chinook-edges")
    pieces, out = directory / "pieces", directory / "out"
    pieces.mkdir()
    shutil.copyfile(SOURCE, directory / SOURCE.name)
    tessera = _import(directory, pieces)
    _ok(
        "build",
        FIXTURE / "pattern.yaml",
        "--pieces",
        pieces,
        "--model",
        MODEL,
        "-o",
        out,
        cwd=directory,
    )
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    return Built(directory, pieces, tessera, out / "default.mosaic", report)


def _q(built: Built, sql: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    with built.open() as m:
        return m.query(sql, params, limits=ALL_ROWS)


def _no_vectors_pattern(directory: Path, *, piece_pin: str | None = None) -> Path:
    """The fixture's pattern with vectors off (knowledge hash unchanged, section 3.6)."""
    text = (FIXTURE / "pattern.yaml").read_text(encoding="utf-8")
    if piece_pin is not None:
        _, pinned = _pinned()
        assert pinned in text
        text = text.replace(pinned, piece_pin)
    pattern = directory / "pattern.yaml"
    pattern.write_text(text + "\nmosaics:\n  default: {vectors: false}\n", encoding="utf-8")
    return pattern


# --- Canonical order (section 3.6) -------------------------------------------------------------


def test_node_rows_follow_utf8_byte_order_of_the_id_not_the_number(built: Built) -> None:
    """3.6: node row ids are the rank of `id` by bytes: Track:10 sorts before Track:2."""
    rows = _q(built, "SELECT nid, id FROM node ORDER BY nid")
    assert [nid for nid, _ in rows] == list(range(1, len(rows) + 1))
    ids = [str(i) for _, i in rows]
    assert ids == sorted(ids, key=lambda s: s.encode("utf-8"))
    assert ids.index("Track:10") < ids.index("Track:2")
    assert ids.index("Track:1") < ids.index("Track:10") < ids.index("Track:100")


def test_edge_rows_follow_src_type_dst_order(built: Built) -> None:
    """3.6: edge row ids are the rank of (src, type, dst, qualifier), dense from 1."""
    by_nid = _q(built, "SELECT eid, src, type, dst, qualifier FROM edge ORDER BY eid")
    assert [r[0] for r in by_nid] == list(range(1, len(by_nid) + 1))
    # Node ids are ranked by their bytes, so comparing nid compares the ids' bytes.
    sort_keys = [(r[1], str(r[2]).encode("utf-8"), r[3], str(r[4]).encode("utf-8")) for r in by_nid]
    assert sort_keys == sorted(sort_keys)


# --- Keys, ids, labels, properties against the source (3.4, 5.2) -------------------------------

LABELS = {
    "Artist": ("Artist", "ArtistId", "Name"),
    "Album": ("Album", "AlbumId", "Title"),
    "Track": ("Track", "TrackId", "Name"),
    "Genre": ("Genre", "GenreId", "Name"),
    "MediaType": ("MediaType", "MediaTypeId", "Name"),
    "Playlist": ("Playlist", "PlaylistId", "Name"),
    "Employee": ("Employee", "EmployeeId", "LastName"),
    "Customer": ("Customer", "CustomerId", "LastName"),
}


@pytest.mark.parametrize("node_type", sorted(LABELS))
def test_every_row_of_a_table_is_one_node_with_its_label_byte_for_byte(
    built: Built, node_type: str
) -> None:
    """5.2, 3.4: the id is `<Type>:<key>` with the key as text; the label is the source's text."""
    table, pk, column = LABELS[node_type]
    expected = {
        f"{node_type}:{k}": label for k, label in _source(f"SELECT {pk}, {column} FROM {table}")
    }
    found = dict(_q(built, "SELECT id, label FROM node WHERE type = ?", (node_type,)))
    assert found == expected
    for node_id, key in _q(built, "SELECT id, key FROM node WHERE type = ?", (node_type,)):
        assert node_id == f"{node_type}:{key}"
        assert isinstance(key, str)


def test_non_ascii_labels_are_kept_as_the_source_wrote_them(built: Built) -> None:
    """3.1/3.6: text is UTF-8, compared by bytes; no normalisation changes a label."""
    rows = dict(_q(built, "SELECT id, label FROM node WHERE id IN ('Artist:6', 'Artist:18')"))
    assert rows["Artist:6"].encode("utf-8") == "Antônio Carlos Jobim".encode()
    assert rows["Artist:18"] == "Chico Science & Nação Zumbi"


def test_same_label_on_two_rows_is_two_nodes(built: Built) -> None:
    """3.4: (type, key) is the identity, never the label: two playlists are named Music."""
    rows = _q(built, "SELECT id FROM node WHERE type = 'Playlist' AND label = 'Music' ORDER BY id")
    assert rows == [("Playlist:1",), ("Playlist:8",)]
    tracks = _q(built, "SELECT count(*) FROM node WHERE type = 'Track' AND label = 'Wrathchild'")
    assert tracks == [(5,)]


def test_track_properties_equal_the_source_and_keep_their_kinds(built: Built) -> None:
    """3.4: props are a JSON object; numbers stay numbers, text stays text."""
    source = _source(
        "SELECT TrackId, Name, Composer, Milliseconds, Bytes, UnitPrice FROM Track ORDER BY TrackId"
    )
    found = {
        str(k): json.loads(str(p))
        for k, p in _q(built, "SELECT key, props FROM node WHERE type = 'Track'")
    }
    assert len(found) == len(source)
    for track_id, name, composer, ms, size, price in source:
        props = found[str(track_id)]
        assert props.get("name") == name
        assert props.get("composer") == composer  # absent and null both read as None
        assert props["milliseconds"] == ms and isinstance(props["milliseconds"], int)
        assert props["bytes"] == size and isinstance(props["bytes"], int)
        assert props["unit_price"] == price


def test_a_track_without_composer_has_no_composer_value(built: Built) -> None:
    """3.4 + 5.2: NULL in the source is no value. Track 65 has a NULL Composer."""
    assert _source("SELECT Composer FROM Track WHERE TrackId = 65") == [(None,)]
    [(props,)] = _q(built, "SELECT props FROM node WHERE id = 'Track:65'")
    assert json.loads(str(props)).get("composer") is None  # absent, or JSON null; never a stand-in


def test_declared_property_kinds_match_the_values_stored(built: Built) -> None:
    """3.4: values SHOULD match the declared kinds; 7.1 step 7 declares them."""
    allowed = {
        "text": {"text"},
        "integer": {"integer"},
        "number": {"integer", "real"},
        "boolean": {"true", "false"},
        "json": None,
    }
    types = _q(built, "SELECT name, props FROM type WHERE kind = 'node'")
    mismatches = []
    for name, declared in types:
        for prop, kind in json.loads(str(declared)).items():
            ok = allowed[kind]
            if ok is None:
                continue
            for (jt,) in _q(
                built,
                "SELECT DISTINCT json_type(props, '$.' || ?) FROM node WHERE type = ? "
                "AND json_type(props, '$.' || ?) IS NOT NULL "
                "AND json_type(props, '$.' || ?) <> 'null'",
                (prop, name, prop, prop),
            ):
                if jt not in ok:
                    mismatches.append((name, prop, kind, jt))
    assert not mismatches


def test_the_type_table_declares_exactly_the_pattern_types(built: Built) -> None:
    """7.1 step 7: every type in scope is declared, with `describe` and `key` of the pattern."""
    pattern = load((FIXTURE / "pattern.yaml").read_text(encoding="utf-8"), "pattern.yaml").data
    nodes = _q(
        built, "SELECT name, description, key_prop FROM type WHERE kind = 'node' ORDER BY name"
    )
    assert nodes == sorted((n, t["describe"], t["key"]) for n, t in pattern["types"].items())
    edges = _q(built, "SELECT name, from_type, to_type FROM type WHERE kind = 'edge' ORDER BY name")
    assert edges == sorted((n, e["from"], e["to"]) for n, e in pattern["edges"].items())
    names = {str(n) for n, _, _ in nodes}
    assert not names & {"Invoice", "InvoiceLine", "PlaylistTrack"}  # left out by the settings


# --- Edges against the source (5.3 map, 3.9) ---------------------------------------------------

EDGE_SOURCES = {
    "by": ("SELECT AlbumId, ArtistId FROM Album", "Album", "Artist"),
    "on_album": ("SELECT TrackId, AlbumId FROM Track WHERE AlbumId IS NOT NULL", "Track", "Album"),
    "in_genre": ("SELECT TrackId, GenreId FROM Track WHERE GenreId IS NOT NULL", "Track", "Genre"),
    "encoded_as": (
        "SELECT TrackId, MediaTypeId FROM Track WHERE MediaTypeId IS NOT NULL",
        "Track",
        "MediaType",
    ),
    "contains": ("SELECT PlaylistId, TrackId FROM PlaylistTrack", "Playlist", "Track"),
    "reports_to": (
        "SELECT EmployeeId, ReportsTo FROM Employee WHERE ReportsTo IS NOT NULL",
        "Employee",
        "Employee",
    ),
    "supported_by": (
        "SELECT CustomerId, SupportRepId FROM Customer WHERE SupportRepId IS NOT NULL",
        "Customer",
        "Employee",
    ),
}


@pytest.mark.parametrize("edge_type", sorted(EDGE_SOURCES))
def test_each_edge_type_joins_exactly_the_pairs_the_source_rows_name(
    built: Built, edge_type: str
) -> None:
    """5.3 map: the edges are the foreign keys of the database, no more and no fewer."""
    sql, src_type, dst_type = EDGE_SOURCES[edge_type]
    expected = {(f"{src_type}:{a}", f"{dst_type}:{b}") for a, b in _source(sql)}
    rows = _q(built, "SELECT src, dst, qualifier FROM v_edge WHERE type = ?", (edge_type,))
    assert {(str(s), str(d)) for s, d, _ in rows} == expected
    assert len(rows) == len(expected)  # no duplicate pair
    assert all(q == "" for _, _, q in rows)  # 3.4: qualifier empty unless two edges join a pair


def test_the_top_employee_has_no_manager_edge(built: Built) -> None:
    """A NULL foreign key makes no edge (Employee 1 reports to nobody)."""
    assert _q(
        built, "SELECT count(*) FROM v_edge WHERE type = 'reports_to' AND src = 'Employee:1'"
    ) == [(0,)]
    assert _q(built, "SELECT count(*) FROM v_edge WHERE type = 'reports_to'") == [(7,)]


def test_a_playlist_with_no_tracks_still_has_a_node_and_no_edge(built: Built) -> None:
    """A node needs evidence, not edges: every playlist is a node, empty ones have none."""
    empty = _source(
        "SELECT PlaylistId FROM Playlist p WHERE NOT EXISTS "
        "(SELECT 1 FROM PlaylistTrack t WHERE t.PlaylistId = p.PlaylistId)"
    )
    for (pid,) in empty:
        assert _q(built, "SELECT count(*) FROM node WHERE id = ?", (f"Playlist:{pid}",)) == [(1,)]
        assert _q(built, "SELECT count(*) FROM v_edge WHERE src = ?", (f"Playlist:{pid}",)) == [
            (0,)
        ]


def test_link_counts_are_those_of_a_busy_playlist(built: Built) -> None:
    """3.2: link_count holds edges per node, type and direction; checked against the source."""
    [(busiest, n)] = _source(
        "SELECT PlaylistId, count(*) FROM PlaylistTrack GROUP BY PlaylistId "
        "ORDER BY 2 DESC, 1 LIMIT 1"
    )
    assert n > 1000
    assert _q(
        built,
        "SELECT count(*) FROM v_edge WHERE type = 'contains' AND src = ?",
        (f"Playlist:{busiest}",),
    ) == [(n,)]


# --- Evidence (3.5, 3.9) -----------------------------------------------------------------------

LOCATOR = re.compile(r"^[^;=]+=[^;]*(;[^;=]+=[^;]*)*$")


def test_every_node_and_edge_has_extracted_evidence_from_the_database(built: Built) -> None:
    """3.5, 3.9: at least one evidence row each; extracted rows have no confidence."""
    assert _q(
        built,
        "SELECT count(*) FROM node n "
        "WHERE NOT EXISTS (SELECT 1 FROM evidence v WHERE v.nid = n.nid)",
    ) == [(0,)]
    assert _q(
        built,
        "SELECT count(*) FROM edge e "
        "WHERE NOT EXISTS (SELECT 1 FROM evidence v WHERE v.eid = e.eid)",
    ) == [(0,)]
    assert _q(
        built,
        "SELECT count(*) FROM evidence WHERE method <> 'extracted' OR confidence IS NOT NULL "
        "OR via IS NOT NULL",
    ) == [(0,)]


def test_every_locator_is_a_list_of_name_value_pairs_and_names_a_row(built: Built) -> None:
    """3.5: a locator is a `;`-separated list of `name=value`, most specific last."""
    locators = [str(r[0]) for r in _q(built, "SELECT DISTINCT locator FROM evidence")]
    assert locators
    for locator in locators:
        assert LOCATOR.match(locator), locator
        assert "row=" in locator, locator
        assert "\x00" not in locator


def test_distinct_rows_never_share_evidence(built: Built) -> None:
    """3.5: no two evidence rows are equal in all the identifying columns."""
    assert _q(
        built,
        "SELECT count(*) FROM (SELECT nid, eid, prop, sid, locator, method, producer,"
        " confidence, via"
        " FROM evidence GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9 HAVING count(*) > 1)",
    ) == [(0,)]


def test_the_original_source_is_the_database_with_its_hash_and_the_piece_is_the_tessera(
    built: Built,
) -> None:
    """3.2, 3.5: `sid` names the original source, never a piece; hashes pin both."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    [sha] = [f["sha256"] for f in manifest["fixtures"] if f["name"] == "chinook"]
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == sha
    name, pinned = _pinned()
    sources = _q(built, "SELECT id, kind, hash FROM source ORDER BY id")
    pieces = [s for s in sources if s[1] in ("tessera", "mosaic")]
    assert pieces == [(name, "tessera", pinned)]
    originals = [s for s in sources if s[1] not in ("tessera", "mosaic")]
    assert [(i, h) for i, _, h in originals] == [
        (f"{name}/{str(i).split('/', 1)[1]}", sha) for i, _, _ in originals
    ]
    assert len(originals) == 1
    assert originals[0][1] == "database"
    sources_in_evidence = {r[0] for r in _q(built, "SELECT DISTINCT source FROM v_evidence")}
    assert sources_in_evidence == {originals[0][0]}


def test_a_contains_edge_keeps_the_two_keys_of_its_row_in_the_locator(built: Built) -> None:
    """3.5: an edge made by a two-key row cites that row (most specific last)."""
    rows = _q(
        built,
        "SELECT edge_src, edge_dst, locator FROM v_evidence WHERE edge_type = 'contains' "
        "AND edge_src = 'Playlist:1'",
    )
    assert len(rows) == len(_source("SELECT 1 FROM PlaylistTrack WHERE PlaylistId = 1"))
    for src, dst, locator in rows:
        track = str(dst).split(":", 1)[1]
        assert str(locator).endswith(f"row=1/{track}"), (src, dst, locator)


# --- Header, report, hashes (3.3, 3.6, 3.7, 7.2) -----------------------------------------------


def test_the_header_names_the_target_and_the_hash_of_the_pattern_bytes(built: Built) -> None:
    """3.3: pattern_hash is the SHA-256 of the pattern file's bytes; target is its name."""
    [(kind, fmt, target, pattern_hash, settings, producer)] = _q(
        built,
        "SELECT kind, format_version, target, pattern_hash, settings, producer FROM header",
    )
    assert (kind, fmt, target) == ("mosaic", "0.1", "default")
    assert pattern_hash == hashlib.sha256((FIXTURE / "pattern.yaml").read_bytes()).hexdigest()
    assert isinstance(json.loads(str(settings)), dict)
    assert re.fullmatch(r"[^/\s]+/\S+", str(producer))
    assert built.report["pattern_hash"] == pattern_hash
    assert built.report["target"] == "default"


def test_the_vector_hash_is_the_sha256_of_the_vectors_in_node_order(built: Built) -> None:
    """3.7: 48-byte `bits`, one per node, concatenated in `nid` order, hashed."""
    rows = _q(built, "SELECT v.nid, v.bits FROM vector v ORDER BY v.nid")
    assert [nid for nid, _ in rows] == [
        n for (n,) in _q(built, "SELECT nid FROM node ORDER BY nid")
    ]
    assert all(isinstance(b, bytes) and len(b) == 48 for _, b in rows)
    digest = hashlib.sha256(b"".join(b for _, b in rows)).hexdigest()
    expected = load_expected(FIXTURE)["default"]
    assert digest == expected.vector_hash
    # Two different nodes do not all share one vector: the embedding saw their text.
    assert len({b for _, b in rows}) > 4000


def test_the_report_lists_no_conflict_stale_reference_or_weak_id_for_one_keyed_piece(
    built: Built,
) -> None:
    """7.2: one piece with natural keys gives nothing to report in these entries."""
    report = built.report
    assert report["outcome"] == "built" and report["reason"] in (None, "")
    for entry in ("conflicts", "alias_conflicts", "stale_references", "mentions", "weak_ids"):
        assert not report[entry], entry
    schema = json.loads((SPEC / "build-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)


def test_the_report_counts_equal_the_rows_of_the_mosaic(built: Built) -> None:
    """7.2: node and edge counts per type; every declared type appears."""
    counts = built.report["counts"]
    assert isinstance(counts, dict)
    nodes = dict(_q(built, "SELECT type, count(*) FROM node GROUP BY type"))
    edges = dict(_q(built, "SELECT type, count(*) FROM v_edge GROUP BY type"))
    assert counts["nodes"] == nodes and counts["edges"] == edges
    declared = _q(built, "SELECT kind, name FROM type")
    assert set(counts["nodes"]) == {n for k, n in declared if k == "node"}
    assert set(counts["edges"]) == {n for k, n in declared if k == "edge"}


# --- Search (the full-text tier of 3.2 / 8.1) --------------------------------------------------


def test_the_search_index_finds_a_node_by_a_word_of_its_label(built: Built) -> None:
    """3.2: `search` is FTS5 over labels; a word of the label finds the node."""
    rows = _q(
        built,
        "SELECT n.id FROM search s JOIN node n ON n.nid = s.rowid WHERE search MATCH 'label:Jobim' "
        "ORDER BY n.id",
    )
    assert ("Artist:6",) in rows


# --- Determinism and robustness of the flow (4.3, 5.1, 7) --------------------------------------


def test_importing_from_another_directory_by_absolute_path_gives_the_pinned_tessera(
    built: Built, tmp_path: Path
) -> None:
    """4.3: the same database gives the same tessera hash wherever it is read from."""
    elsewhere = tmp_path / "somewhere" / "deeper"
    elsewhere.mkdir(parents=True)
    shutil.copyfile(SOURCE, elsewhere / SOURCE.name)
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    _import(tmp_path, pieces, source=elsewhere / SOURCE.name)
    with open_sealed(pieces / "chinook.tessera") as t:
        assert t.knowledge_hash == _pinned()[1]


def test_the_tessera_does_not_depend_on_the_file_mtime_or_permissions_of_the_source(
    tmp_path: Path,
) -> None:
    """4.3: only the content of the source counts."""
    import os

    copy = tmp_path / SOURCE.name
    shutil.copyfile(SOURCE, copy)
    os.utime(copy, (1, 1))
    copy.chmod(0o444)
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    _import(tmp_path, pieces)
    with open_sealed(pieces / "chinook.tessera") as t:
        assert t.knowledge_hash == _pinned()[1]
    assert copy.read_bytes() == SOURCE.read_bytes()


def test_a_prefix_of_eight_characters_pins_the_same_piece(built: Built, tmp_path: Path) -> None:
    """5.1: a prefix of at least 8 characters MAY be given; the mosaic is the same knowledge."""
    _, pinned = _pinned()
    pattern = _no_vectors_pattern(tmp_path, piece_pin=pinned[:8])
    _ok("build", pattern, "--pieces", built.pieces, "-o", tmp_path / "out", cwd=tmp_path)
    with open_sealed(tmp_path / "out" / "default.mosaic") as m:
        assert m.knowledge_hash == load_expected(FIXTURE)["default"].knowledge_hash
        [(piece_hash,)] = m.query("SELECT hash FROM source WHERE kind = 'tessera'")
    assert piece_hash == pinned  # the file carries the full hash, not the prefix


def test_a_prefix_of_seven_characters_is_a_violation(built: Built, tmp_path: Path) -> None:
    """5.1: a prefix shorter than 8 characters is not a pin."""
    _, pinned = _pinned()
    pattern = _no_vectors_pattern(tmp_path, piece_pin=pinned[:7])
    done = _mosaic("check", pattern, "--pieces", built.pieces, cwd=tmp_path)
    assert done.returncode != 0, done.stdout + done.stderr
    built_ = _mosaic(
        "build", pattern, "--pieces", built.pieces, "-o", tmp_path / "out", cwd=tmp_path
    )
    assert built_.returncode != 0
    assert not (tmp_path / "out" / "default.mosaic").exists()


def test_a_wrong_pin_fails_the_build_and_the_report_says_failed(
    built: Built, tmp_path: Path
) -> None:
    """5.1, 7.1 step 1, 7.2: a piece matching no file stops the build; the report is written."""
    _, pinned = _pinned()
    wrong = pinned[:-1] + ("0" if pinned[-1] != "0" else "1")
    pattern = _no_vectors_pattern(tmp_path, piece_pin=wrong)
    done = _mosaic("build", pattern, "--pieces", built.pieces, "-o", tmp_path / "out", cwd=tmp_path)
    assert done.returncode != 0
    assert not (tmp_path / "out" / "default.mosaic").exists()
    report = json.loads((tmp_path / "out" / "build-report.json").read_text(encoding="utf-8"))
    schema = json.loads((SPEC / "build-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    assert report["outcome"] == "failed" and report["reason"]


def test_the_pattern_alone_does_not_check_without_its_piece(tmp_path: Path) -> None:
    """5.1: a piece that matches no available file is a violation."""
    empty = tmp_path / "empty"
    empty.mkdir()
    done = _mosaic("check", FIXTURE / "pattern.yaml", "--pieces", empty, cwd=tmp_path)
    assert done.returncode != 0, done.stdout + done.stderr


def test_the_piece_is_found_by_its_hash_whatever_the_file_is_called(
    built: Built, tmp_path: Path
) -> None:
    """5.1: which files are available is up to the tool; the pin is a hash, not a file name."""
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    shutil.copyfile(built.tessera, pieces / "renamed-copy.tessera")
    pattern = _no_vectors_pattern(tmp_path)
    _ok("build", pattern, "--pieces", pieces, "-o", tmp_path / "out", cwd=tmp_path)
    with open_sealed(tmp_path / "out" / "default.mosaic") as m:
        assert m.knowledge_hash == load_expected(FIXTURE)["default"].knowledge_hash


def test_two_files_with_the_pinned_hash_are_a_violation(built: Built, tmp_path: Path) -> None:
    """5.1: a pin that matches more than one available file is a violation."""
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    shutil.copyfile(built.tessera, pieces / "chinook.tessera")
    shutil.copyfile(built.tessera, pieces / "chinook-again.tessera")
    pattern = _no_vectors_pattern(tmp_path)
    done = _mosaic("build", pattern, "--pieces", pieces, "-o", tmp_path / "out", cwd=tmp_path)
    assert done.returncode != 0, done.stdout + done.stderr
    assert not (tmp_path / "out" / "default.mosaic").exists()


def test_the_knowledge_hash_does_not_depend_on_where_the_pattern_or_output_are(
    built: Built, tmp_path: Path
) -> None:
    """7: the same inputs give the same knowledge hash, whatever the directories."""
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    pattern = _no_vectors_pattern(deep)
    other = tmp_path / "cwd"
    other.mkdir()
    _ok(
        "build",
        pattern,
        "--pieces",
        built.pieces,
        "-o",
        tmp_path / "x" / "y" / "z",
        cwd=other,
    )
    with open_sealed(tmp_path / "x" / "y" / "z" / "default.mosaic") as m:
        assert m.knowledge_hash == load_expected(FIXTURE)["default"].knowledge_hash


def test_a_build_with_vectors_but_no_model_fails_and_writes_no_mosaic(
    built: Built, tmp_path: Path
) -> None:
    """6, 7.2: vectors need the model; a failed build writes no mosaic, still a report."""
    done = _mosaic(
        "build",
        FIXTURE / "pattern.yaml",
        "--pieces",
        built.pieces,
        "-o",
        tmp_path / "out",
        cwd=tmp_path,
    )
    assert done.returncode != 0, done.stdout + done.stderr
    assert not (tmp_path / "out" / "default.mosaic").exists()


def test_an_unknown_target_is_refused(built: Built, tmp_path: Path) -> None:
    """5.4, 7: the target must be one the pattern declares."""
    done = _mosaic(
        "build",
        _no_vectors_pattern(tmp_path),
        "--pieces",
        built.pieces,
        "--target",
        "nothing",
        "-o",
        tmp_path / "out",
        cwd=tmp_path,
    )
    assert done.returncode != 0
    assert not (tmp_path / "out" / "nothing.mosaic").exists()


# --- Untrusted or corrupt files (3.8, 10) ------------------------------------------------------


def _copy_and_edit(source: Path, target: Path, sql: str) -> Path:
    shutil.copyfile(source, target)
    db = sqlite3.connect(target)
    try:
        db.execute(sql)
        db.commit()
    finally:
        db.close()
    return target


def test_a_mosaic_with_one_label_changed_is_refused(built: Built, tmp_path: Path) -> None:
    """3.8 rule 3, 3.9: the knowledge hash is recomputed; a changed label does not match."""
    bad = _copy_and_edit(
        built.mosaic,
        tmp_path / "bad.mosaic",
        "UPDATE node SET label = 'Altered' WHERE id = 'Artist:6'",
    )
    done = _mosaic("check", bad, "--pieces", built.pieces, cwd=tmp_path)
    assert done.returncode != 0, done.stdout + done.stderr


def test_a_mosaic_with_one_vector_changed_is_refused(built: Built, tmp_path: Path) -> None:
    """3.8 rule 3, 3.7: the vector hash binds each vector to its node."""
    bad = _copy_and_edit(
        built.mosaic,
        tmp_path / "bad.mosaic",
        "UPDATE vector SET bits = zeroblob(48) WHERE nid = (SELECT min(nid) FROM vector)",
    )
    done = _mosaic("check", bad, cwd=tmp_path)
    assert done.returncode != 0, done.stdout + done.stderr


def test_a_tessera_with_one_row_changed_is_not_a_piece_of_the_pattern(
    built: Built, tmp_path: Path
) -> None:
    """5.1, 3.8: the pin is the knowledge hash; an altered tessera has another and is refused."""
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    _copy_and_edit(
        built.tessera, pieces / "chinook.tessera", "UPDATE node SET label = 'X' WHERE rowid = 1"
    )
    pattern = _no_vectors_pattern(tmp_path)
    done = _mosaic("build", pattern, "--pieces", pieces, "-o", tmp_path / "out", cwd=tmp_path)
    assert done.returncode != 0, done.stdout + done.stderr
    assert not (tmp_path / "out" / "default.mosaic").exists()


def test_a_truncated_mosaic_is_refused(built: Built, tmp_path: Path) -> None:
    """3.8, 10: a corrupt file is an error, not a crash."""
    data = built.mosaic.read_bytes()
    bad = tmp_path / "truncated.mosaic"
    bad.write_bytes(data[: len(data) // 2])
    done = _mosaic("check", bad, cwd=tmp_path)
    assert done.returncode != 0
    assert "Traceback" not in done.stderr


def test_the_checked_mosaic_without_its_pieces_still_passes(built: Built, tmp_path: Path) -> None:
    """3.9: notice and pin checks need the pieces only where they are given."""
    _ok("check", built.mosaic, cwd=tmp_path)
