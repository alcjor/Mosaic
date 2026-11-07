"""The Chinook fixture end to end (Specification 0.1, section 11; plan M3.3).

The source, one SQLite database, is downloaded and checked against its pinned SHA-256 by
``scripts/fetch_fixtures.py`` (never committed). ``mosaic import sqlite`` makes the tessera with
``conformance/fixtures/chinook/settings.yaml``, ``mosaic check`` checks the pattern beside it
against that tessera, ``mosaic build`` builds it with vectors (the model of section 6, fetched
and checked by ``scripts/fetch_model.py``), and ``mosaic check`` checks the tessera and the
mosaic. The whole flow runs twice, each time in a new, empty directory: both runs give the
tessera hash that ``pattern.yaml`` pins (section 5.1), the same mosaic, knowledge hash and vector
hash, and a build report valid against ``spec/build-report.schema.json`` (section 7.2). Each
run's hashes and model are those ``expected-hashes.json`` records. The test prints the hashes,
file sizes and timings of both runs, for the PR (run it with ``-s``).

Chinook is "the first case with several linked types" (section 11): eight node types and seven
edge types, among them a foreign key to its own table (``reports_to``) and a table whose primary
key is two foreign keys (``PlaylistTrack``, one ``contains`` edge per row, plan M3.13).
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from mosaic_format.reader import open as open_sealed
from mosaic_format.yaml_core import load

from tests.conftest import MODEL, REPO, SPEC
from tests.fixtures.expected import differences, load_expected
from tests.fixtures.test_netflix import Run, _timed

BUILD_BUDGET_SECONDS = 15 * 60
"""ADR-007, as for the Netflix mosaic: building with vectors takes under 15 minutes."""

FIXTURE = REPO / "conformance" / "fixtures" / "chinook"
TARGET = "default"
"""The pattern's one target (it has no ``mosaics``, section 5.4); its file is ``default.mosaic``."""
SOURCE = REPO / "conformance" / "fixtures" / "downloads" / "chinook" / "Chinook_Sqlite.sqlite"
NODES = {
    "Artist": 275,
    "Album": 347,
    "Track": 3503,
    "Genre": 25,
    "MediaType": 5,
    "Playlist": 18,
    "Employee": 8,
    "Customer": 59,
}
"""One node per row of each table the settings name: the rows of the pinned database."""
EDGES = {
    "by": 347,
    "on_album": 3503,
    "in_genre": 3503,
    "encoded_as": 3503,
    "contains": 8715,
    "reports_to": 7,
    "supported_by": 59,
}
"""One edge per non-NULL foreign key value, and one per row of ``PlaylistTrack``."""

pytestmark = pytest.mark.slow


def _pinned_piece() -> tuple[str, str]:
    """The name and hash of the one piece that ``pattern.yaml`` pins."""
    pattern = load((FIXTURE / "pattern.yaml").read_text(encoding="utf-8"), "pattern.yaml").data
    [piece] = pattern["pieces"]
    name, _, pinned = piece.partition("@")
    return name, pinned


def _run(directory: Path) -> Run:
    """Import, check, build and check in ``directory``, which starts empty."""
    directory.mkdir()
    assert not any(directory.iterdir())
    name, _ = _pinned_piece()
    pieces, out = directory / "pieces", directory / "out"
    pieces.mkdir()
    shutil.copyfile(SOURCE, directory / SOURCE.name)
    tessera = pieces / f"{name}.tessera"
    pattern = FIXTURE / "pattern.yaml"
    settings = FIXTURE / "settings.yaml"
    seconds: dict[str, float] = {}
    _timed(
        seconds,
        "import",
        *("import", "sqlite", SOURCE.name, "--settings", settings, "-o", tessera),
        cwd=directory,
    )
    _timed(seconds, "check pattern", "check", pattern, "--pieces", pieces, cwd=directory)
    _timed(
        seconds,
        "build",
        *("build", pattern, "--pieces", pieces, "--model", MODEL, "-o", out),
        cwd=directory,
    )
    mosaic = out / f"{TARGET}.mosaic"
    _timed(seconds, "check tessera", "check", tessera, cwd=directory)
    _timed(seconds, "check mosaic", "check", mosaic, "--pieces", pieces, cwd=directory)
    with open_sealed(tessera) as t:
        tessera_hash = t.knowledge_hash
    with open_sealed(mosaic) as m:
        mosaic_hash = m.knowledge_hash
        ((vector_hash, embed_model, vectors, nodes),) = m.query(
            "SELECT vector_hash, embed_model, (SELECT count(*) FROM vector), "
            "(SELECT count(*) FROM node) FROM header"
        )
    # The source is only read (principle 8): byte-identical, nothing made beside it.
    assert (directory / SOURCE.name).read_bytes() == SOURCE.read_bytes()
    assert sorted(p.name for p in directory.iterdir()) == [SOURCE.name, "out", "pieces"]
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    return Run(
        tessera_hash=tessera_hash,
        tessera_size=tessera.stat().st_size,
        mosaic_hash=mosaic_hash,
        vector_hash=None if vector_hash is None else str(vector_hash),
        embed_model=None if embed_model is None else str(embed_model),
        vectors=int(str(vectors)),
        nodes=int(str(nodes)),
        mosaic_size=mosaic.stat().st_size,
        mosaic_bytes=mosaic.read_bytes(),
        report=report,
        seconds=seconds,
    )


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Run, Run]:
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
    base = tmp_path_factory.mktemp("chinook")
    first, second = _run(base / "first"), _run(base / "second")
    for label, run in (("first", first), ("second", second)):
        timings = ", ".join(f"{step} {s:.1f} s" for step, s in run.seconds.items())
        print(
            f"\nchinook {label}: tessera {run.tessera_hash} ({run.tessera_size:,} bytes); "
            f"mosaic {run.mosaic_hash} vectors {run.vector_hash} ({run.mosaic_size:,} bytes, "
            f"{run.nodes:,} nodes); {timings}"
        )
    return first, second


def test_the_imported_tessera_has_the_hash_the_pattern_pins(runs: tuple[Run, Run]) -> None:
    _, pinned = _pinned_piece()
    for run in runs:
        assert run.tessera_hash == pinned


def test_each_build_has_the_expected_hashes(runs: tuple[Run, Run]) -> None:
    """Section 11: the fixture holds "the expected mosaic"; plan M3.3."""
    expected = load_expected(FIXTURE)
    for run in runs:
        found = differences(
            expected,
            TARGET,
            knowledge_hash=run.mosaic_hash,
            vector_hash=run.vector_hash,
            embed_model=run.embed_model,
        )
        assert not found, "\n".join(found)


def test_two_clean_builds_give_the_same_mosaic(runs: tuple[Run, Run]) -> None:
    first, second = runs
    assert first.tessera_hash == second.tessera_hash
    assert first.mosaic_hash == second.mosaic_hash
    assert first.vector_hash == second.vector_hash
    assert first.mosaic_bytes == second.mosaic_bytes
    assert first.report == second.report


def test_the_build_report_is_valid_and_names_the_mosaic(runs: tuple[Run, Run]) -> None:
    schema = json.loads((SPEC / "build-report.schema.json").read_text(encoding="utf-8"))
    for run in runs:
        Draft202012Validator(schema).validate(run.report)
        assert run.report["outcome"] == "built"
        assert run.report["knowledge_hash"] == run.mosaic_hash
        assert run.report["vector_hash"] == run.vector_hash
        assert run.report["file_size"] == run.mosaic_size


def test_the_mosaic_holds_every_linked_type_of_the_pattern(runs: tuple[Run, Run]) -> None:
    counts = runs[0].report["counts"]
    assert isinstance(counts, dict)
    assert counts["nodes"] == NODES
    assert counts["edges"] == EDGES


def test_the_mosaic_has_one_vector_per_node_and_names_the_model(runs: tuple[Run, Run]) -> None:
    for run in runs:
        assert run.vectors == run.nodes == sum(NODES.values())
        assert run.embed_model == (
            "snowflake-arctic-embed-xs@"
            "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
        )


def test_the_build_with_vectors_takes_under_15_minutes(runs: tuple[Run, Run]) -> None:
    for run in runs:
        assert run.seconds["build"] < BUILD_BUDGET_SECONDS


def test_a_playlist_links_straight_to_its_tracks(runs: tuple[Run, Run], tmp_path: Path) -> None:
    """Plan M3.13: each row of PlaylistTrack is one edge from the playlist to the track."""
    mosaic = tmp_path / "chinook.mosaic"
    mosaic.write_bytes(runs[0].mosaic_bytes)
    with open_sealed(mosaic) as m:
        assert m.query(
            "SELECT count(*) FROM v_edge WHERE type = 'contains' AND src = 'Playlist:18'"
        ) == [(1,)]
        assert m.query(
            "SELECT locator FROM v_evidence WHERE edge_type = 'contains'"
            " AND edge_src = 'Playlist:18'"
        ) == [("file=Chinook_Sqlite.sqlite;table=PlaylistTrack;row=18/597",)]
        assert m.query(
            "SELECT dst FROM v_edge WHERE type = 'reports_to' AND src = 'Employee:2'"
        ) == [("Employee:1",)]
