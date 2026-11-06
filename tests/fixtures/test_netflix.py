"""The Netflix titles fixture end to end (Specification 0.1, section 11; plan M1.2).

The source is downloaded and checked against its pinned SHA-256 by ``scripts/fetch_fixtures.py``
(never committed). ``mosaic import csv`` makes the tessera with
``conformance/fixtures/netflix/settings.yaml``, ``mosaic build`` builds the pattern beside it,
and ``mosaic check`` checks the pattern, the tessera and the mosaic. The whole flow runs twice,
each time in a new, empty directory: both runs give the tessera hash that ``pattern.yaml`` pins
(section 5.1) and the same mosaic knowledge hash, and the build report is valid against
``spec/build-report.schema.json`` (section 7.2). The test prints the hashes, file sizes and
timings of both runs, for the PR (run it with ``-s``).
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

from tests.conftest import REPO, SPEC
from tests.test_cli import entry_point

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
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    return Run(
        tessera_hash=tessera_hash,
        tessera_size=tessera.stat().st_size,
        mosaic_hash=mosaic_hash,
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
    base = tmp_path_factory.mktemp("netflix")
    first, second = _run(base / "first"), _run(base / "second")
    for label, run in (("first", first), ("second", second)):
        timings = ", ".join(f"{step} {s:.1f} s" for step, s in run.seconds.items())
        print(
            f"\nnetflix {label}: tessera {run.tessera_hash} ({run.tessera_size:,} bytes); "
            f"mosaic {run.mosaic_hash} ({run.mosaic_size:,} bytes); {timings}"
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
