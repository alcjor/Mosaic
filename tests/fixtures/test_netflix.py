"""The Netflix titles fixture end to end (Specification 0.1, section 11; plan M1.2).

The source is downloaded and checked against its pinned SHA-256 by ``scripts/fetch_fixtures.py``
(never committed). ``mosaic import csv`` makes the tessera with
``conformance/fixtures/netflix/settings.yaml``, ``mosaic build`` builds the pattern beside it,
and ``mosaic check`` checks the pattern, the tessera and the mosaic. The whole flow runs twice,
each time in a new, empty directory: both runs give the tessera hash that ``pattern.yaml`` pins
(section 5.1) and the same mosaic knowledge hash, and the build report is valid against
``spec/build-report.schema.json`` (section 7.2). The pattern's one target has vectors on (the
default), so ``mosaic build`` gets the model of section 6 with ``--model``, fetched and checked
by ``scripts/fetch_model.py``: both runs give the same vector hash (section 7), one vector per
node, and the knowledge hash of the same target with vectors off (section 3.6). The test prints
the hashes, file sizes and timings of both runs, for the PR (run it with ``-s``).
"""

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from mosaic_format.reader import open as open_sealed
from mosaic_format.yaml_core import load

from tests.conftest import MODEL, REPO, SPEC
from tests.test_cli import entry_point

BUILD_BUDGET_SECONDS = 15 * 60
"""ADR-007: building the Netflix mosaic, vectors included, takes under 15 minutes."""

FIXTURE = REPO / "conformance" / "fixtures" / "netflix"
SOURCE = REPO / "conformance" / "fixtures" / "downloads" / "netflix-titles" / "netflix_titles.csv"
TYPES = ("Title", "Person", "Country", "Genre", "Year")
EDGES = ("directed_by", "features", "made_in", "listed_in", "released_in")

pytestmark = pytest.mark.slow


@dataclass(frozen=True)
class Run:
    tessera_hash: str
    tessera_size: int
    mosaic_hash: str
    vector_hash: str | None
    embed_model: str | None
    vectors: int
    nodes: int
    mosaic_size: int
    mosaic_bytes: bytes
    report: dict[str, object]
    seconds: dict[str, float]


def _mosaic(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(
        [str(entry_point()), *(str(a) for a in args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, f"mosaic {args[0]} failed:\n{done.stdout}{done.stderr}"
    return done


def _timed(seconds: dict[str, float], step: str, *args: str | Path, cwd: Path) -> str:
    started = time.perf_counter()
    out = _mosaic(*args, cwd=cwd).stdout
    seconds[step] = time.perf_counter() - started
    return out


def _pinned_piece() -> tuple[str, str]:
    """The name and hash of the one piece that ``pattern.yaml`` pins."""
    pattern = load((FIXTURE / "pattern.yaml").read_text(encoding="utf-8"), "pattern.yaml").data
    [piece] = pattern["pieces"]
    name, _, pinned = piece.partition("@")
    return name, pinned


def _run(directory: Path) -> Run:
    """Import, build and check in ``directory``, which starts empty."""
    directory.mkdir()
    assert not any(directory.iterdir())
    name, _ = _pinned_piece()
    pieces, out = directory / "pieces", directory / "out"
    pieces.mkdir()
    shutil.copyfile(SOURCE, directory / SOURCE.name)
    tessera = pieces / f"{name}.tessera"
    seconds: dict[str, float] = {}
    settings = FIXTURE / "settings.yaml"
    _timed(
        seconds,
        "import",
        "import",
        "csv",
        SOURCE.name,
        "--settings",
        settings,
        "-o",
        tessera,
        cwd=directory,
    )
    _timed(
        seconds,
        "check pattern",
        "check",
        FIXTURE / "pattern.yaml",
        "--pieces",
        pieces,
        cwd=directory,
    )
    _timed(
        seconds,
        "build",
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
    mosaic = out / "default.mosaic"
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
    assert "ok   netflix-titles" in fetched.stdout, fetched.stdout + fetched.stderr
    model = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "fetch_model.py"), "--dest", str(MODEL)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert model.returncode == 0, model.stdout + model.stderr
    base = tmp_path_factory.mktemp("netflix")
    first, second = _run(base / "first"), _run(base / "second")
    for label, run in (("first", first), ("second", second)):
        timings = ", ".join(f"{step} {s:.1f} s" for step, s in run.seconds.items())
        print(
            f"\nnetflix {label}: tessera {run.tessera_hash} ({run.tessera_size:,} bytes); "
            f"mosaic {run.mosaic_hash} vectors {run.vector_hash} ({run.mosaic_size:,} bytes, "
            f"{run.nodes:,} nodes); {timings}"
        )
    return first, second


def test_the_imported_tessera_has_the_hash_the_pattern_pins(runs: tuple[Run, Run]) -> None:
    _, pinned = _pinned_piece()
    for run in runs:
        assert run.tessera_hash == pinned


def test_two_clean_builds_give_the_same_knowledge_hash(runs: tuple[Run, Run]) -> None:
    first, second = runs
    assert first.tessera_hash == second.tessera_hash
    assert first.mosaic_hash == second.mosaic_hash
    assert first.mosaic_bytes == second.mosaic_bytes
    assert first.report == second.report


def test_the_build_report_is_valid_and_names_the_mosaic(runs: tuple[Run, Run]) -> None:
    schema = json.loads((SPEC / "build-report.schema.json").read_text(encoding="utf-8"))
    for run in runs:
        Draft202012Validator(schema).validate(run.report)
        assert run.report["outcome"] == "built"
        assert run.report["knowledge_hash"] == run.mosaic_hash
        assert run.report["file_size"] == run.mosaic_size


def test_the_mosaic_holds_every_type_and_edge_type_of_the_pattern(runs: tuple[Run, Run]) -> None:
    counts = runs[0].report["counts"]
    assert isinstance(counts, dict)
    assert set(counts["nodes"]) == set(TYPES)
    assert set(counts["edges"]) == set(EDGES)
    assert all(n > 0 for n in [*counts["nodes"].values(), *counts["edges"].values()])
    # Every row of the source is one title.
    assert counts["nodes"]["Title"] == 8807


# --- vectors (plan M2.7) ----------------------------------------------------------------------


def test_the_mosaic_has_one_vector_per_node_and_names_the_model(runs: tuple[Run, Run]) -> None:
    for run in runs:
        assert run.vectors == run.nodes > 0
        assert run.embed_model == (
            "snowflake-arctic-embed-xs@"
            "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
        )
        assert run.vector_hash is not None
        assert run.report["vector_hash"] == run.vector_hash


def test_two_clean_builds_give_the_same_vector_hash(runs: tuple[Run, Run]) -> None:
    first, second = runs
    assert first.vector_hash == second.vector_hash


def test_the_build_with_vectors_takes_under_15_minutes(runs: tuple[Run, Run]) -> None:
    for run in runs:
        assert run.seconds["build"] < BUILD_BUDGET_SECONDS


def test_the_knowledge_hash_is_that_of_the_same_target_with_vectors_off(
    runs: tuple[Run, Run], tmp_path: Path
) -> None:
    name, _ = _pinned_piece()
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    built = runs[0]
    text = (FIXTURE / "pattern.yaml").read_text(encoding="utf-8")
    assert "\nmosaics:" not in text  # the one target is `default`, with every default
    pattern = tmp_path / "pattern.yaml"
    pattern.write_text(text + "\nmosaics:\n  default: {vectors: false}\n", encoding="utf-8")
    # The tessera of the first run, imported again here (same source, same settings).
    shutil.copyfile(SOURCE, tmp_path / SOURCE.name)
    tessera = pieces / f"{name}.tessera"
    settings = FIXTURE / "settings.yaml"
    _mosaic("import", "csv", SOURCE.name, "--settings", settings, "-o", tessera, cwd=tmp_path)
    _mosaic("build", pattern, "--pieces", pieces, "-o", tmp_path / "out", cwd=tmp_path)
    with open_sealed(tmp_path / "out" / "default.mosaic") as m:
        assert m.knowledge_hash == built.mosaic_hash
        assert m.query("SELECT vector_hash, embed_model FROM header") == [(None, None)]
