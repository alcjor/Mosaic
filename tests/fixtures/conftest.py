"""Slow fixtures shared by every Netflix test module: one pair of clean builds per inputs.

``test_netflix.py``, ``test_netflix_read.py`` and ``test_netflix_read_edges.py`` used to build the
Netflix mosaic with vectors four times per run. They now share one session-wide pair of clean
builds, reused across runs while nothing it depends on changes (``build_cache``).
"""

import dataclasses
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from tests.conftest import MODEL, REPO
from tests.fixtures import build_cache
from tests.fixtures.test_netflix import FIXTURE, SOURCE, TARGET, Run, _run

NETFLIX_INPUTS = [
    SOURCE,
    FIXTURE / "settings.yaml",
    FIXTURE / "pattern.yaml",
    MODEL,
    REPO / "uv.lock",
    REPO / "packages",
    REPO / "spec",
    REPO / "tests" / "fixtures" / "test_netflix.py",
    REPO / "tests" / "fixtures" / "build_cache.py",
]
"""Everything the Netflix build depends on: source, settings, pattern, model, dependencies, the
builder and format code, the normative files, and the build procedure itself."""


@dataclass(frozen=True)
class NetflixBuilds:
    first: Run
    second: Run
    mosaic: Path
    """A copy of the first build's mosaic, for this session only."""
    key: str
    reused: bool


@pytest.fixture(scope="session")
def netflix_fetched() -> None:
    """The source and the model, fetched and checked by their pinned SHA-256."""
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


def _record(directory: Path) -> tuple[dict[str, object], Path]:
    run = _run(directory)
    record = {f.name: getattr(run, f.name) for f in dataclasses.fields(Run)}
    del record["mosaic_bytes"]
    return record, directory / "out" / f"{TARGET}.mosaic"


@pytest.fixture(scope="session")
def netflix_builds(
    netflix_fetched: None, tmp_path_factory: pytest.TempPathFactory
) -> NetflixBuilds:
    builds = build_cache.twice(
        "netflix", NETFLIX_INPUTS, _record, tmp_path_factory.mktemp("netflix")
    )
    first, second = (
        Run(**cast(dict[str, Any], record), mosaic_bytes=file.read_bytes())
        for record, file in zip(builds.records, builds.files, strict=True)
    )
    how = (
        "reused the two clean builds recorded for these inputs"
        if builds.reused
        else "built twice from clean directories"
    )
    print(f"\nnetflix: {how} (inputs {builds.key[:12]}; MOSAIC_FRESH_BUILDS=1 rebuilds)")
    return NetflixBuilds(first, second, builds.files[0], builds.key, builds.reused)


@pytest.fixture(scope="session")
def built(netflix_builds: NetflixBuilds) -> tuple[Path, Run]:
    """The Netflix mosaic built with vectors (the first clean build), and its run."""
    assert netflix_builds.first.vectors == netflix_builds.first.nodes > 0
    return netflix_builds.mosaic, netflix_builds.first
