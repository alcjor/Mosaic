"""The Netflix titles mosaic, read side (Specification 0.1, section 11; plan M2.12).

Section 11: the Netflix titles case checks "the whole flow end to end on the simplest input:
import, build, seal, open in the kit and the viewer". The mosaic is built with vectors, as in
``tests/fixtures/test_netflix.py`` (the source and the model fetched and checked by their
pinned SHA-256), then opened in the kit inside Chromium with ``kit/scripts/open-time.ts``, which
recomputes the knowledge hash and the vector hash on open (section 3.8 step 3): both equal those
``mosaic_format`` computes, and a copy with one vector byte changed is refused, naming the hash.
Run it with ``-s`` for the hashes, size and timings.
"""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from mosaic_format.hashes import knowledge_hash, vector_hash

from tests.conftest import MODEL, REPO
from tests.fixtures.test_netflix import Run, _run

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Run]:
    """The Netflix mosaic, built with vectors in a new, empty directory."""
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
    directory = tmp_path_factory.mktemp("netflix-read") / "run"
    run = _run(directory)
    assert run.vectors == run.nodes > 0
    return directory / "out" / "default.mosaic", run


def _open_in_kit(path: Path) -> subprocess.CompletedProcess[str]:
    bun = shutil.which("bun")
    assert bun, "bun is needed to bundle the kit (CLAUDE.md, Commands)"
    return subprocess.run(
        [bun, "kit/scripts/open-time.ts", str(path), "--runs", "3"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def test_the_kit_opens_the_netflix_mosaic_with_both_hashes_checked(
    built: tuple[Path, Run],
) -> None:
    path, run = built
    with sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True) as con:
        expected = (knowledge_hash(con), vector_hash(con))
    assert expected == (run.mosaic_hash, run.vector_hash)
    opened = _open_in_kit(path)
    assert opened.returncode == 0, opened.stderr
    result = json.loads(opened.stdout.strip().splitlines()[-1])
    print(
        f"\nnetflix in the kit (Chromium): {run.nodes:,} nodes, {result['bytes']:,} bytes; "
        f"open with hash checks {result['runs_ms']} ms, median {result['median_ms']} ms; "
        f"knowledge {result['knowledge_hash']} vector {result['vector_hash']}; "
        f"build {run.seconds['build']:.1f} s"
    )
    assert (result["knowledge_hash"], result["vector_hash"]) == expected


def test_the_kit_refuses_the_netflix_mosaic_with_one_vector_changed(
    built: tuple[Path, Run], tmp_path: Path
) -> None:
    path, _ = built
    changed = tmp_path / "changed.mosaic"
    shutil.copyfile(path, changed)
    with sqlite3.connect(changed) as con:
        ((nid, bits),) = con.execute("SELECT nid, bits FROM vector ORDER BY nid LIMIT 1")
        flipped = bytes([bits[0] ^ 0x80]) + bits[1:]
        con.execute("UPDATE vector SET bits = ? WHERE nid = ?", (flipped, nid))
    con.close()
    opened = _open_in_kit(changed)
    assert opened.returncode != 0
    assert "vector hash" in opened.stderr, opened.stderr
