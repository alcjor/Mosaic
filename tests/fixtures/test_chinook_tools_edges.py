"""Edge cases of the kit's tool cases on the Chinook mosaic (plan M3.4; verifier; slow).

Written from Specification 0.1 sections 8.1, 8.2, 8.5, 8.6 and 11 and ``spec/answers.schema.json``,
not from the kit. The mosaic is built as ``test_chinook.py`` builds it. Three kinds of check:

* the expected answers against the Chinook source database itself (the pinned SQLite file), read
  with ``sqlite3``: what a person who knows the source table would expect each case to show;
* the same run twice, and on a second build, giving the same bytes (principle 5, determinism);
* calls beyond the cases, answered by the kit and compared with a reference written from the
  words of section 8.6 (kinds in ``where``, ``order`` groups and nulls, pages, the cut marker).
"""

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import MODEL, REPO
from tests.fixtures import test_chinook
from tests.fixtures.tool_cases import FILE, SCHEMA, load

pytestmark = pytest.mark.slow

CALLS = """
import { readFileSync } from "node:fs";
import { openFile, loadEmbedder } from "@@KIT@@/src/index.js";
const [mosaic, modelDir] = process.argv.slice(2);
const embedder = modelDir === "-" ? undefined : await loadEmbedder({
  model: new Uint8Array(readFileSync(`${modelDir}/onnx/model_quantized.onnx`)),
  tokenizer: new Uint8Array(readFileSync(`${modelDir}/tokenizer.json`)),
});
const file = await openFile(new Uint8Array(readFileSync(mosaic)), "chinook.mosaic",
  embedder ? { embedder } : {});
const out: unknown[] = [];
for (const call of JSON.parse(readFileSync(0, "utf8"))) {
  out.push(await (file as any)[call.tool](call.arguments));
}
console.log(JSON.stringify(out));
"""
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
MARKER = "…"


def _cut(text: str | None, limit: int) -> str | None:
    """Section 8.2: text over ``limit`` characters is cut there and ends in the marker."""
    return text if text is None or len(text) <= limit else text[:limit] + MARKER


def _by(text: str) -> bytes:
    return text.encode("utf-8")


class World:
    """The mosaic built once, the kit's way of being called, and the source database."""

    def __init__(self, root: Path, second: Path) -> None:
        self.mosaic = root / "chinook.mosaic"
        self.second = second
        self.script = root / "calls.ts"
        self.script.write_text(CALLS.replace("@@KIT@@", str(REPO / "kit")), encoding="utf-8")
        self.db = sqlite3.connect(f"file:{test_chinook.SOURCE}?mode=ro", uri=True)

    def call(self, calls: list[dict[str, Any]], *, vectors: bool = True) -> list[dict[str, Any]]:
        """The kit's answers to ``calls`` (tool, arguments), each valid against the schema."""
        bun = shutil.which("bun")
        assert bun
        done = subprocess.run(
            [bun, str(self.script), str(self.mosaic), str(MODEL) if vectors else "-"],
            input=json.dumps(calls),
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        answers: list[dict[str, Any]] = json.loads(done.stdout)
        assert len(answers) == len(calls)
        for call, answer in zip(calls, answers, strict=True):
            errors = [e.message for e in VALIDATOR.iter_errors(answer)]
            assert not errors, f"{call}: {errors}"
            assert answer["tool"] == call["tool"]
        return answers

    def one(self, tool: str, **arguments: Any) -> dict[str, Any]:
        return self.call([{"tool": tool, "arguments": arguments}])[0]

    def data(self, tool: str, **arguments: Any) -> dict[str, Any]:
        answer = self.one(tool, **arguments)
        assert "data" in answer, answer
        data: dict[str, Any] = answer["data"]
        return data

    def error(self, tool: str, **arguments: Any) -> dict[str, Any]:
        answer = self.one(tool, **arguments)
        assert "error" in answer, answer
        error: dict[str, Any] = answer["error"]
        return error


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    fetched = subprocess.run(
        [sys.executable, "-I", str(REPO / "scripts" / "fetch_fixtures.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert "ok   chinook" in fetched.stdout, fetched.stdout + fetched.stderr
    model = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "fetch_model.py"), "--dest", str(MODEL)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert model.returncode == 0, model.stdout + model.stderr
    root = tmp_path_factory.mktemp("chinook-tools-edges")
    first = test_chinook._run(root / "build-1")
    second = test_chinook._run(root / "build-2")
    (root / "chinook.mosaic").write_bytes(first.mosaic_bytes)
    (root / "second.mosaic").write_bytes(second.mosaic_bytes)
    return World(root, root / "second.mosaic")


def _run_cases(mosaic: Path, cwd: Path = REPO) -> str:
    bun = shutil.which("bun")
    assert bun
    command = [bun, str(REPO / "kit/scripts/run-cases.ts"), str(mosaic), str(FILE)]
    command += ["--model", str(MODEL)]
    done = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


# --- determinism (principle 5) ------------------------------------------------------------------


def test_the_same_cases_run_twice_give_the_same_bytes(world: World) -> None:
    assert _run_cases(world.mosaic) == _run_cases(world.mosaic)


def test_a_second_build_of_the_mosaic_gives_the_same_answers_to_every_case(world: World) -> None:
    assert _run_cases(world.mosaic) == _run_cases(world.second)


def test_the_cases_give_the_same_answers_whatever_the_working_directory(
    world: World, tmp_path: Path
) -> None:
    assert _run_cases(world.mosaic, tmp_path) == _run_cases(world.mosaic)


def test_a_mosaic_of_the_same_bytes_gives_the_knowledge_hash_every_answer_carries(
    world: World,
) -> None:
    expected = load()["cases"]["get-track"]["answer"]["mosaic"]
    assert world.one("get", id="Track:1")["mosaic"] == expected


# --- the expected answers against the source database -------------------------------------------


def _rows(world: World, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    return world.db.execute(sql, args).fetchall()


def test_get_track_gives_the_source_row(world: World) -> None:
    ((name, composer, ms, nbytes, price),) = _rows(
        world,
        "SELECT Name, Composer, Milliseconds, Bytes, UnitPrice FROM Track WHERE TrackId = 1",
    )
    data = load()["cases"]["get-track"]["answer"]["data"]
    assert data["label"] == name
    assert data["props"] == {
        "bytes": nbytes,
        "composer": composer,
        "milliseconds": ms,
        "name": name,
        "unit_price": price,
    }
    (on_playlists,) = _rows(world, "SELECT count(*) FROM PlaylistTrack WHERE TrackId = 1")[0]
    links = {(x["edge"], x["direction"]): x["count"] for x in data["links"]}
    assert links[("contains", "in")] == on_playlists
    assert links[("on_album", "out")] == links[("in_genre", "out")] == 1


def test_get_employee_gives_the_source_row(world: World) -> None:
    ((last, first, title, city, country, hired),) = _rows(
        world,
        "SELECT LastName, FirstName, Title, City, Country, HireDate FROM Employee"
        " WHERE EmployeeId = 2",
    )
    data = load()["cases"]["get-employee"]["answer"]["data"]
    assert data["label"] == last
    assert data["props"] == {
        "city": city,
        "country": country,
        "first_name": first,
        "hire_date": hired,
        "last_name": last,
        "title": title,
    }


def test_neighbors_totals_are_the_source_row_counts(world: World) -> None:
    cases = load()["cases"]
    (tracks,) = _rows(world, "SELECT count(*) FROM Track WHERE AlbumId = 1")[0]
    assert cases["neighbors-album-in"]["answer"]["data"]["total"] == tracks
    (listed,) = _rows(world, "SELECT count(*) FROM PlaylistTrack WHERE PlaylistId = 18")[0]
    assert cases["neighbors-playlist-out"]["answer"]["data"]["total"] == listed
    reports = {r[0] for r in _rows(world, "SELECT EmployeeId FROM Employee WHERE ReportsTo = 1")}
    shown = {e["id"] for e in cases["neighbors-manager"]["answer"]["data"]["edges"]}
    assert shown == {f"Employee:{i}" for i in reports}


def test_neighbors_album_in_lists_every_track_of_the_album(world: World) -> None:
    """Section 8.2: cut at 20 with the total (the album has 10 tracks: all of them show)."""
    edges = load()["cases"]["neighbors-album-in"]["answer"]["data"]["edges"]
    tracks = {f"Track:{i}" for (i,) in _rows(world, "SELECT TrackId FROM Track WHERE AlbumId = 1")}
    assert {e["id"] for e in edges} == tracks


def test_table_customer_country_is_the_source_table_filtered(world: World) -> None:
    rows = _rows(
        world,
        "SELECT 'Customer:' || c.CustomerId, c.FirstName, c.LastName, c.Country, e.LastName"
        " FROM Customer c LEFT JOIN Employee e ON e.EmployeeId = c.SupportRepId"
        " WHERE c.Country = 'Brazil'",
    )
    expected = sorted(
        ([r[0], r[1], r[2], r[3], [r[4]]] for r in rows), key=lambda r: _by(str(r[0]))
    )
    data = load()["cases"]["table-customer-country"]["answer"]["data"]
    assert data["rows"] == expected
    assert data["total"] == len(expected)


def test_table_track_where_composer_contains_mercury_is_ordered_by_length_descending(
    world: World,
) -> None:
    rows = _rows(
        world,
        "SELECT TrackId, Name, Composer, Milliseconds FROM Track WHERE Composer LIKE '%mercury%'",
    )
    expected = sorted(rows, key=lambda r: (-r[3], _by(f"Track:{r[0]}")))
    data = load()["cases"]["table-track-where"]["answer"]["data"]
    assert [r[0] for r in data["rows"]] == [f"Track:{r[0]}" for r in expected][:20]
    assert data["total"] == len(expected)
    for row, source in zip(data["rows"], expected, strict=False):
        assert row[1:4] == [source[1], source[2], source[3]]


def test_table_page_2_of_jazz_tracks_is_the_second_page_of_the_source(world: World) -> None:
    rows = _rows(
        world,
        "SELECT t.TrackId, t.Name, g.Name FROM Track t JOIN Genre g ON g.GenreId = t.GenreId"
        " WHERE lower(g.Name) LIKE '%jazz%'",
    )
    ordered = sorted(rows, key=lambda r: _by(f"Track:{r[0]}"))
    data = load()["cases"]["table-page-2"]["answer"]["data"]
    assert data["total"] == len(ordered)
    assert [r[0] for r in data["rows"]] == [f"Track:{r[0]}" for r in ordered[20:40]]
    assert [r[2] for r in data["rows"]] == [[r[2]] for r in ordered[20:40]]


def test_table_albums_by_gives_every_album_of_the_artist_with_its_artist_label(
    world: World,
) -> None:
    rows = _rows(
        world,
        "SELECT a.AlbumId, a.Title, r.Name FROM Album a JOIN Artist r ON r.ArtistId = a.ArtistId"
        " WHERE lower(r.Name) LIKE '%led zeppelin%'",
    )
    expected = sorted(([f"Album:{r[0]}", r[1], [r[2]]] for r in rows), key=lambda r: _by(str(r[0])))
    data = load()["cases"]["table-albums-by"]["answer"]["data"]
    assert data["rows"] == expected[:20]
    assert data["total"] == len(expected)


def test_cite_cases_give_the_source_hash_and_locator_of_the_source_row(world: World) -> None:
    digest = hashlib.sha256(test_chinook.SOURCE.read_bytes()).hexdigest()
    cases = load()["cases"]
    node = cases["cite-node"]["answer"]["data"]["evidence"][0]
    edge = cases["cite-edge"]["answer"]["data"]["evidence"][0]
    assert node["source_hash"] == edge["source_hash"] == digest
    assert node["locator"] == "file=Chinook_Sqlite.sqlite;table=Track;row=1"
    assert edge["locator"] == "file=Chinook_Sqlite.sqlite;table=PlaylistTrack;row=18/597"
    assert _rows(world, "SELECT 1 FROM PlaylistTrack WHERE PlaylistId = 18 AND TrackId = 597")


def test_find_exact_key_gives_the_artist_whose_key_is_the_query(world: World) -> None:
    ((name,),) = _rows(world, "SELECT Name FROM Artist WHERE ArtistId = 90")
    first = load()["cases"]["find-exact-key"]["answer"]["data"]["results"][0]
    assert first == {"id": "Artist:90", "type": "Artist", "label": name, "match": "exact"}


def test_find_finds_every_node_labelled_exactly_iron_maiden(world: World) -> None:
    named = {
        f"{table}:{i}"
        for table, key, column in (
            ("Artist", "ArtistId", "Name"),
            ("Album", "AlbumId", "Title"),
            ("Track", "TrackId", "Name"),
        )
        for (i,) in _rows(world, f"SELECT {key} FROM {table} WHERE {column} = 'Iron Maiden'")
    }
    assert named
    shown = {r["id"] for r in world.data("find", query="Iron Maiden", limit=20)["results"]}
    assert named <= shown


# --- text is cut with the marker (section 8.2) --------------------------------------------------


def _long_track(world: World) -> tuple[int, str]:
    ((track_id, name),) = _rows(
        world, "SELECT TrackId, Name FROM Track WHERE length(Name) > 120 ORDER BY TrackId"
    )
    assert len(name) == 123
    return track_id, name


def test_a_label_over_120_characters_is_cut_with_the_marker_in_get(world: World) -> None:
    track_id, name = _long_track(world)
    data = world.data("get", id=f"Track:{track_id}")
    assert data["label"] == name[:120] + MARKER
    assert len(data["label"]) == 121


def test_a_cut_label_is_cut_in_find_neighbors_and_table_cells_too(world: World) -> None:
    track_id, name = _long_track(world)
    node = f"Track:{track_id}"
    cut = _cut(name, 120)
    found = world.data("find", query=node, limit=1)["results"][0]
    assert (found["id"], found["label"]) == (node, cut)
    ((album,),) = _rows(world, "SELECT AlbumId FROM Track WHERE TrackId = ?", track_id)
    edges = world.data("neighbors", id=f"Album:{album}", direction="in")["edges"]
    assert [e["label"] for e in edges if e["id"] == node] == [cut]
    table = world.data(
        "table",
        type="Track",
        columns=["label", "name"],
        where={"column": "name", "op": "=", "value": name},
    )
    assert table["rows"] == [[node, cut, name]], "label cut at 120, property text only at 400"


def test_an_edge_cell_cuts_the_labels_it_lists_at_120_characters(world: World) -> None:
    """Section 8.6: labels at 120 characters, in edge cells too (here a playlist's tracks)."""
    track_id, name = _long_track(world)
    ((playlist,),) = _rows(
        world, "SELECT min(PlaylistId) FROM PlaylistTrack WHERE TrackId = ?", track_id
    )
    cell = world.data(
        "table",
        type="Playlist",
        columns=["contains"],
        where={"column": "key", "op": "=", "value": str(playlist)},
    )["rows"][0][1]
    assert _cut(name, 120) in cell
    assert name not in cell
    assert all(label is None or len(label) <= 121 for label in cell)


# --- find: a total that does not depend on the limit (section 8.2) ------------------------------


def test_the_total_of_a_find_does_not_depend_on_the_limit(world: World) -> None:
    """Section 8.2: lists are cut with *the* total count; cutting at 5 or at 20 is one total."""
    totals = {
        limit: world.data("find", query="Iron Maiden", limit=limit)["total"] for limit in (5, 20)
    }
    assert totals[5] == totals[20], totals


def test_the_total_of_a_find_is_not_below_the_results_listed_at_any_limit(world: World) -> None:
    for limit in (1, 2, 7, 8, 9, 20):
        data = world.data("find", query="Iron Maiden", limit=limit)
        assert len(data["results"]) == min(limit, len(data["results"]))
        assert data["total"] >= len(data["results"])


def test_a_find_at_a_smaller_limit_lists_a_prefix_of_the_larger_one(world: World) -> None:
    big = [r["id"] for r in world.data("find", query="Iron Maiden", limit=20)["results"]]
    for limit in (1, 5, 8, 9):
        small = [r["id"] for r in world.data("find", query="Iron Maiden", limit=limit)["results"]]
        assert small == big[:limit]


# --- unknown ids name the closest matches from find (section 8.1) -------------------------------


@pytest.mark.parametrize("tool", ["get", "neighbors", "cite"])
def test_an_unknown_id_names_matches_that_find_gives_for_that_id(world: World, tool: str) -> None:
    """Section 8.1: "naming the closest matches from ``find``". The spec does not say which query
    (the id, or its key with or without the type); any of the three is read as allowed here."""
    missing = "Artist:Queen"
    suggestions = world.error(tool, id=missing)["suggestions"]
    assert suggestions
    found: set[str] = set()
    for arguments in (
        {"query": missing},
        {"query": "Queen"},
        {"query": "Queen", "type": "Artist"},
    ):
        found |= {r["id"] for r in world.data("find", limit=20, **arguments)["results"]}
    assert set(suggestions) <= found


def test_an_unknown_id_error_suggests_only_nodes_that_exist(world: World) -> None:
    for missing in ("Artist:Queen", "Album:0", "Track:99999", "Genre:Rok", "x"):
        error = world.error("get", id=missing)
        for suggestion in error["suggestions"]:
            assert world.data("get", id=suggestion)["id"] == suggestion


# --- calls beyond the cases ---------------------------------------------------------------------


def test_neighbors_without_a_direction_gives_both_directions_in_one_list(world: World) -> None:
    both = world.data("neighbors", id="Album:1")
    out = world.data("neighbors", id="Album:1", direction="out")
    into = world.data("neighbors", id="Album:1", direction="in")
    assert both["total"] == out["total"] + into["total"]
    assert {(e["edge"], e["direction"], e["id"]) for e in both["edges"]} == {
        (e["edge"], e["direction"], e["id"]) for e in out["edges"] + into["edges"]
    }
    assert world.data("neighbors", id="Album:1", direction="both") == both


def test_neighbors_total_counts_past_the_limit(world: World) -> None:
    (n,) = _rows(world, "SELECT count(*) FROM PlaylistTrack WHERE PlaylistId = 1")[0]
    data = world.data("neighbors", id="Playlist:1", edge="contains", limit=3)
    assert len(data["edges"]) == 3
    assert data["total"] == n


def test_neighbors_of_a_node_with_no_edges_of_that_kind_is_an_empty_success(world: World) -> None:
    """Section 8.1: only an unknown id is an error; a known node with no such edge has none."""
    data = world.data("neighbors", id="Genre:1", edge="by", direction="out")
    assert data["edges"] == [] and data["total"] == 0


def test_a_cite_of_an_edge_between_unlinked_nodes_is_an_error(world: World) -> None:
    error = world.error("cite", **{"from": "Track:1", "type": "on_album", "to": "Album:2"})
    assert error["code"] in {"unknown_edge", "unknown_id"}


def test_a_cite_of_an_edge_in_the_wrong_direction_is_an_error(world: World) -> None:
    error = world.error("cite", **{"from": "Album:1", "type": "on_album", "to": "Track:1"})
    assert error["code"] == "unknown_edge"


def test_a_cite_of_an_edge_with_an_unknown_node_is_an_unknown_id_error(world: World) -> None:
    error = world.error("cite", **{"from": "Track:1", "type": "on_album", "to": "Album:999999"})
    assert error["code"] == "unknown_id"


def test_every_node_of_a_type_cites_at_least_one_evidence_row(world: World) -> None:
    """Section 3.5: every node has evidence, so cite never answers an empty list for a node."""
    for node in (
        "Artist:1",
        "Album:347",
        "Track:3503",
        "Genre:25",
        "MediaType:5",
        "Playlist:18",
        "Employee:8",
        "Customer:59",
    ):
        data = world.data("cite", id=node)
        assert data["total"] >= 1 and data["evidence"]


def test_every_kind_of_edge_cites_at_least_one_evidence_row(world: World) -> None:
    for edge in (
        {"from": "Album:1", "type": "by", "to": "Artist:1"},
        {"from": "Track:1", "type": "on_album", "to": "Album:1"},
        {"from": "Track:1", "type": "in_genre", "to": "Genre:1"},
        {"from": "Track:1", "type": "encoded_as", "to": "MediaType:1"},
        {"from": "Employee:2", "type": "reports_to", "to": "Employee:1"},
        {"from": "Customer:1", "type": "supported_by", "to": "Employee:3"},
    ):
        assert world.data("cite", **edge)["total"] >= 1, edge


# --- table: kinds, groups, nulls, pages (section 8.6) -------------------------------------------


def _tracks(world: World) -> dict[str, dict[str, Any]]:
    out = {}
    for tid, name, composer, ms, nbytes, price in _rows(
        world, "SELECT TrackId, Name, Composer, Milliseconds, Bytes, UnitPrice FROM Track"
    ):
        out[f"Track:{tid}"] = {
            "name": name,
            "label": _cut(name, 120),
            "key": str(tid),
            "summary": None,
            "composer": _cut(composer, 400),
            "milliseconds": ms,
            "bytes": nbytes,
            "unit_price": price,
        }
    return out


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "text" if isinstance(value, str) else "other"


def _holds(cell: Any, op: str, value: Any) -> bool:
    if op == "contains":
        return isinstance(cell, str) and str(value).lower() in cell.lower()
    same = cell is not None and _kind(cell) == _kind(value)
    if op == "!=":
        return not (same and cell == value)
    if not same:
        return False
    a, b = (_by(cell), _by(value)) if isinstance(cell, str) else (cell, value)
    return {"=": a == b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def _expected_table(
    world: World, columns: list[str], where: list[dict[str, Any]], page: int = 1
) -> tuple[list[list[Any]], int]:
    nodes = _tracks(world)
    kept = [
        i
        for i in sorted(nodes, key=_by)
        if all(_holds(nodes[i][c["column"]], c["op"], c["value"]) for c in where)
    ]
    rows = [[i] + [nodes[i][c] for c in columns] for i in kept[20 * (page - 1) : 20 * page]]
    return rows, len(kept)


@pytest.mark.parametrize(
    "where",
    [
        [{"column": "milliseconds", "op": ">", "value": 5_000_000}],
        [{"column": "milliseconds", "op": "<=", "value": 1000}],
        [{"column": "milliseconds", "op": ">=", "value": 5_286_953}],
        [{"column": "unit_price", "op": "=", "value": 1.99}],
        [{"column": "unit_price", "op": "!=", "value": 0.99}],
        [{"column": "composer", "op": "!=", "value": "AC/DC"}],
        [{"column": "composer", "op": "=", "value": "AC/DC"}],
        [{"column": "composer", "op": "<", "value": "B"}],
        [{"column": "composer", "op": "contains", "value": "MERCURY"}],
        [{"column": "composer", "op": "contains", "value": "É"}],
        [{"column": "milliseconds", "op": "=", "value": "343719"}],
        [{"column": "milliseconds", "op": "!=", "value": "343719"}],
        [{"column": "milliseconds", "op": "=", "value": True}],
        [{"column": "milliseconds", "op": "contains", "value": "343"}],
        [{"column": "name", "op": "<", "value": "a"}],
        [{"column": "key", "op": "=", "value": "1"}],
        [{"column": "summary", "op": "=", "value": ""}],
        [{"column": "summary", "op": "!=", "value": ""}],
        [
            {"column": "composer", "op": "contains", "value": "young"},
            {"column": "milliseconds", "op": ">", "value": 300_000},
        ],
    ],
)
def test_table_where_matches_a_reference_of_section_8_6(
    world: World, where: list[dict[str, Any]]
) -> None:
    columns = ["name", "composer", "milliseconds", "unit_price", "key", "summary"]
    data = world.data("table", type="Track", columns=columns, where=where)
    rows, total = _expected_table(world, columns, where)
    assert data["total"] == total
    assert data["rows"] == rows


def test_table_where_given_as_one_condition_or_a_list_of_one_is_the_same(world: World) -> None:
    condition = {"column": "milliseconds", "op": ">", "value": 5_000_000}
    assert world.data("table", type="Track", where=condition) == world.data(
        "table", type="Track", where=[condition]
    )


def test_table_notequal_holds_for_nodes_with_no_value_and_equal_does_not(world: World) -> None:
    (nulls,) = _rows(world, "SELECT count(*) FROM Track WHERE Composer IS NULL")[0]
    ne = world.data("table", type="Track", where={"column": "composer", "op": "!=", "value": "x"})
    assert ne["total"] == 3503
    eq = world.data("table", type="Track", where={"column": "composer", "op": "=", "value": ""})
    assert eq["total"] == 0
    assert nulls > 0, "the check needs tracks with no composer"


@pytest.mark.parametrize("page", [1, 2, 175, 176, 177, 10_000])
def test_table_pages_cut_at_20_rows_and_stay_empty_past_the_end(world: World, page: int) -> None:
    data = world.data("table", type="Track", columns=["name"], page=page)
    rows, total = _expected_table(world, ["name"], [], page)
    assert data["page"] == page
    assert data["total"] == total == 3503
    assert data["rows"] == rows


def test_table_page_zero_and_page_one_and_a_half_are_refused(world: World) -> None:
    for page in (0, -1, 1.5):
        assert world.error("table", type="Track", page=page)["code"] == "bad_argument"


def test_table_default_columns_are_label_then_the_declared_properties(world: World) -> None:
    data = world.data("table", type="Track")
    assert data["columns"][:2] == ["id", "label"]
    assert len(data["columns"]) <= 21
    assert sorted(data["columns"][2:]) == [
        "bytes",
        "composer",
        "milliseconds",
        "name",
        "unit_price",
    ]


def _ordered(
    ids: list[str], nodes: dict[str, dict[str, Any]], column: str, desc: bool
) -> list[str]:
    """Section 8.6: by value (UTF-8 bytes), ties by id ascending in both directions."""
    groups: dict[bytes, list[str]] = {}
    for i in ids:
        groups.setdefault(_by(nodes[i][column]), []).append(i)
    return [i for k in sorted(groups, reverse=desc) for i in sorted(groups[k], key=_by)]


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_table_order_sorts_text_by_utf8_bytes_with_ties_by_id_in_both_directions(
    world: World, direction: str
) -> None:
    nodes = _tracks(world)
    data = world.data(
        "table",
        type="Track",
        columns=["composer"],
        order={"column": "composer", "direction": direction},
    )
    has = [i for i in nodes if nodes[i]["composer"] is not None]
    expected = _ordered(has, nodes, "composer", direction == "desc")
    assert [r[0] for r in data["rows"]] == expected[:20]


def test_table_order_descending_ends_with_the_nodes_that_have_no_value(world: World) -> None:
    last_page = (3503 + 19) // 20
    for direction in ("asc", "desc"):
        page = world.data(
            "table",
            type="Track",
            columns=["composer"],
            order={"column": "composer", "direction": direction},
            page=last_page,
        )
        assert page["rows"][-1][1] is None, direction


def test_table_order_by_two_columns_breaks_ties_with_the_second_then_the_id(world: World) -> None:
    nodes = _tracks(world)
    order = [{"column": "unit_price", "direction": "desc"}, "milliseconds"]
    data = world.data("table", type="Track", columns=["unit_price", "milliseconds"], order=order)
    expected = sorted(
        nodes,
        key=lambda i: (-nodes[i]["unit_price"], nodes[i]["milliseconds"], _by(i)),
    )
    assert [r[0] for r in data["rows"]] == expected[:20]


def test_table_order_with_no_direction_is_ascending(world: World) -> None:
    plain = world.data("table", type="Track", columns=["milliseconds"], order="milliseconds")
    asc = world.data(
        "table",
        type="Track",
        columns=["milliseconds"],
        order={"column": "milliseconds", "direction": "asc"},
    )
    assert plain == asc


def test_table_order_by_an_edge_column_sorts_the_lists_by_their_json_text(world: World) -> None:
    data = world.data("table", type="Track", columns=["in_genre"], order="in_genre")
    cells = [row[1] for row in data["rows"]]
    texts = [json.dumps(c, ensure_ascii=False) for c in cells]
    assert texts == sorted(texts, key=_by)


def test_table_edge_cell_lists_labels_in_node_id_order_and_is_not_cut_at_20(world: World) -> None:
    """Section 8.6: an edge cell is not cut at 20 items; Playlist:1 holds 3,290 tracks, but the
    edge leaves Playlist: the cell is the list of every track."""
    (n,) = _rows(world, "SELECT count(*) FROM PlaylistTrack WHERE PlaylistId = 1")[0]
    data = world.data(
        "table",
        type="Playlist",
        columns=["contains"],
        where={"column": "key", "op": "=", "value": "1"},
    )
    cell = data["rows"][0][1]
    assert len(cell) == n and n > 20


def test_table_unknown_column_in_where_or_order_is_an_error_not_an_empty_answer(
    world: World,
) -> None:
    assert world.error("table", type="Track", order="nope")["code"] == "unknown_column"
    where = {"column": "Name", "op": "=", "value": "x"}
    assert world.error("table", type="Track", where=where)["code"] == "unknown_column", (
        "column names are exact: property names are lowercase here"
    )


def test_table_where_with_no_conditions_or_more_than_20_is_refused(world: World) -> None:
    one = {"column": "name", "op": "contains", "value": "a"}
    assert world.error("table", type="Track", where=[])["code"] == "bad_argument"
    assert world.error("table", type="Track", where=[one] * 21)["code"] == "bad_argument"
    assert world.data("table", type="Track", where=[one] * 20)["total"] > 0


def test_table_columns_over_20_or_repeated_or_empty_are_refused(world: World) -> None:
    assert world.error("table", type="Track", columns=[])["code"] == "bad_argument"
    assert world.error("table", type="Track", columns=["name", "name"])["code"] == "bad_argument"
    many = [
        "name",
        "composer",
        "milliseconds",
        "bytes",
        "unit_price",
        "label",
        "key",
        "summary",
        "on_album",
        "in_genre",
        "encoded_as",
    ]
    assert world.data("table", type="Track", columns=many)["columns"] == ["id", *many]


# --- odd input to find and the other tools (section 8.1, 10) ------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "a\u0000b",
        "\u0000",
        "'; DROP TABLE node; --",
        'AND OR NOT NEAR(" ")',
        '"unterminated',
        "*",
        "Ü" * 300,
        "\U0001f3b5",
        " ",
        "\n",
        "a" * 5000,
        "Track:1\u0000",
        "Track:",
        ":",
    ],
)
def test_find_answers_odd_queries_with_data_or_a_named_error_never_a_crash(
    world: World, query: str
) -> None:
    answer = world.one("find", query=query, limit=3)
    if "error" in answer:
        assert answer["error"]["code"] in {"bad_argument", "limit_exceeded"}
    else:
        assert len(answer["data"]["results"]) <= 3


def test_find_text_matching_ignores_case(world: World) -> None:
    upper = {r["id"] for r in world.data("find", query="IRON MAIDEN", limit=5)["results"]}
    lower = {r["id"] for r in world.data("find", query="iron maiden", limit=5)["results"]}
    assert upper == lower


def test_find_with_a_type_never_lists_another_type_in_any_tier(world: World) -> None:
    for query in ("Track:1", "rock", "calm music for studying"):
        for result in world.data("find", query=query, type="Genre")["results"]:
            assert result["type"] == "Genre"


def test_find_without_the_model_has_no_vector_matches_and_still_answers(world: World) -> None:
    answer = world.call(
        [{"tool": "find", "arguments": {"query": "calm music for studying"}}], vectors=False
    )[0]
    assert all(r["match"] != "vector" for r in answer["data"]["results"])


def test_the_tool_arguments_of_other_tools_are_refused_when_unknown(world: World) -> None:
    assert world.error("get", id="Track:1", limit=3)["code"] == "bad_argument"
    assert world.error("neighbors", id="Track:1", page=2)["code"] == "bad_argument"
    assert world.error("find", query="x", direction="out")["code"] == "bad_argument"


def test_tool_answers_are_json_text_the_same_on_two_calls(world: World) -> None:
    calls = [
        {"tool": "find", "arguments": {"query": "rock"}},
        {"tool": "get", "arguments": {"id": "Playlist:1"}},
        {"tool": "neighbors", "arguments": {"id": "Playlist:1"}},
        {"tool": "table", "arguments": {"type": "Customer"}},
        {"tool": "cite", "arguments": {"id": "Customer:1"}},
    ]
    assert json.dumps(world.call(calls)) == json.dumps(world.call(calls))
