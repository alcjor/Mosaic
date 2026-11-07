"""Edge cases of the Netflix read side (plan M2.12; Specification 0.1 sections 6, 8.1, 8.5).

Slow, and written from the spec's words. The Netflix mosaic is built with vectors (the source and
the model fetched and checked by their pinned SHA-256, as in ``test_netflix_read.py``), then
``mosaic view --model DIR`` (answer A on #117) is driven in Chromium with
``viewer/scripts/browse.ts --url``. The ranking of the vector tier is checked against an oracle
made with the builder's native embedder and the spec's scoring (section 6: the dot product of the
full-precision, normalised query vector with the stored vector read as +1 and -1): runtimes differ
a little (section 6, Determinism), so the page's list must agree with the oracle's on most of its
entries, not all.
"""

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from mosaic_build.mosaic import vectors as v

from tests.conftest import MODEL, REPO
from tests.fixtures.test_netflix_read import QUERY, TITLE, Run
from tests.test_cli import entry_point

pytestmark = pytest.mark.slow

RESULT_LIMIT = 20
"""Section 8.2: lists are cut at 20 items."""
RANK = {"exact": 0, "text": 1, "vector": 2}
AGREEMENT = 15
"""Of the oracle's first 20 vector matches, at least this many are in the page's list."""


@pytest.fixture(scope="module")
def netflix(request: pytest.FixtureRequest) -> tuple[Path, Run]:
    """The Netflix mosaic built with vectors (``built`` in tests/fixtures/conftest.py)."""
    return request.getfixturevalue("built")  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def bun() -> str:
    found = shutil.which("bun")
    assert found, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    build = subprocess.run(
        [found, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return found


def walk(bun: str, tmp: Path, mosaic: Path, query: str, node: str, model: Path | None) -> Any:
    address = tmp / f"address-{time.monotonic_ns()}.txt"
    recorder = tmp / "browser.py"
    recorder.write_text(
        f"import sys; open({str(address)!r}, 'w').write(sys.argv[1])\n", encoding="utf-8"
    )
    env = {**os.environ, "BROWSER": f"{sys.executable} {recorder} %s"}
    args = [str(entry_point()), "view", str(mosaic), *(["--model", str(model)] if model else [])]
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, text=True)
    try:
        started = time.monotonic()
        while not address.exists() and time.monotonic() - started < 120:
            time.sleep(0.1)
        assert address.exists(), "mosaic view opened no page"
        run = subprocess.run(
            [bun, "viewer/scripts/browse.ts", "--url", address.read_text("utf-8"), query, node],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    finally:
        proc.send_signal(signal.SIGINT)
        proc.communicate(timeout=30)
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout.strip().splitlines()[-1])
    assert seen["errors"] == [] and seen["named"]["banners"] == []
    return seen["named"]


def listed(walked: Any) -> list[tuple[str, str]]:
    return [(r["match"], r["id"]) for r in walked["results"]]


def oracle(mosaic: Path, query: str) -> list[str]:
    """Node ids by the spec's scoring, best first, ties by id (UTF-8 bytes)."""
    q = v.Embedder(MODEL).query(query)
    with sqlite3.connect(f"{mosaic.as_uri()}?mode=ro&immutable=1", uri=True) as con:
        rows = con.execute("SELECT n.id, x.bits FROM vector x JOIN node n USING (nid)").fetchall()
    ids = [r[0] for r in rows]
    bits = np.unpackbits(np.frombuffer(b"".join(r[1] for r in rows), dtype=np.uint8)).reshape(
        -1, 384
    )
    scores = (2.0 * bits - 1.0) @ np.asarray(q, dtype=np.float64)
    order = sorted(range(len(ids)), key=lambda i: (-round(float(scores[i]), 9), ids[i].encode()))
    return [ids[i] for i in order]


def test_the_vector_matches_follow_the_scoring_of_section_6(
    netflix: tuple[Path, Run],
    bun: str,
    tmp_path: Path,
) -> None:
    path, _ = netflix
    seen = walk(bun, tmp_path, path, QUERY, TITLE, MODEL)
    results = listed(seen)
    top = oracle(path, QUERY)[:RESULT_LIMIT]
    page = [i for m, i in results if m == "vector"]
    agree = len(set(page) & set(top))
    print(
        f"\nquery {QUERY!r}: page vector matches {len(page)}; oracle top {len(top)}; "
        f"agreement {agree}; TITLE oracle rank {top.index(TITLE) + 1 if TITLE in top else '>20'}; "
        f"page rank {page.index(TITLE) + 1 if TITLE in page else '-'}"
    )
    assert TITLE in top, "the oracle itself does not list the title"
    assert len(results) <= RESULT_LIMIT
    assert agree >= AGREEMENT, (page, top)


def test_exact_and_text_matches_come_first_and_no_node_is_listed_twice(
    netflix: tuple[Path, Run],
    bun: str,
    tmp_path: Path,
) -> None:
    path, _ = netflix
    seen = walk(bun, tmp_path, path, "Breaking Bad", TITLE, MODEL)
    results = listed(seen)
    ranks = [RANK[m] for m, _ in results]
    assert ranks == sorted(ranks), results
    ids = [i for _, i in results]
    assert len(set(ids)) == len(ids), "a node listed twice"
    assert len(results) <= RESULT_LIMIT
    assert (next(m for m, i in results if i == TITLE)) in {"exact", "text"}


def test_the_model_adds_only_vector_matches_after_the_names_and_text_ones(
    netflix: tuple[Path, Run],
    bun: str,
    tmp_path: Path,
) -> None:
    """Section 3.8: without the model, names and full text; with it, the same, then vectors."""
    path, _ = netflix
    with_model = listed(walk(bun, tmp_path, path, "Breaking Bad", TITLE, MODEL))
    without = listed(walk(bun, tmp_path, path, "Breaking Bad", TITLE, None))
    assert all(m != "vector" for m, _ in without)
    head = [r for r in with_model if r[0] != "vector"]
    assert head == without[: len(head)]
    assert len(head) == len(without) or len(with_model) == RESULT_LIMIT


def test_the_same_query_twice_lists_the_same_matches_in_the_same_order(
    netflix: tuple[Path, Run],
    bun: str,
    tmp_path: Path,
) -> None:
    path, _ = netflix
    first = listed(walk(bun, tmp_path, path, QUERY, TITLE, MODEL))
    second = listed(walk(bun, tmp_path, path, QUERY, TITLE, MODEL))
    assert first == second
