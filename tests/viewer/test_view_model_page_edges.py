"""``mosaic view --model DIR`` in a real browser, on the small conforming files (M2.12).

Answer A on #117: the model reaches the page at runtime from the directory given to
``mosaic view``, checked by its pinned hashes, never bundled into the viewer build. Section 3.8:
a reader that does not support the file's embedding model still opens it and falls back to names
and full text. These tests run the installed ``mosaic view`` with the real model of section 6
(fetched into ``.cache/model``) on ``conformance/reading/`` files, whose vectors are of an
invented model, and drive the page with ``viewer/scripts/browse.ts --url``.
"""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MODEL, REPO
from tests.test_cli import entry_point

pytestmark = pytest.mark.slow

READING = REPO / "conformance" / "reading"
PINNED = {
    "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1",
    "91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854",
}


@pytest.fixture(scope="module")
def bun() -> str:
    found = shutil.which("bun")
    assert found, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    build = subprocess.run(
        [found, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return found


def walk(
    bun: str, tmp: Path, file: Path, query: str, node: str, model: Path | None
) -> dict[str, Any]:
    address = tmp / "address.txt"
    address.unlink(missing_ok=True)
    recorder = tmp / "browser.py"
    recorder.write_text(
        f"import sys; open({str(address)!r}, 'w').write(sys.argv[1])\n", encoding="utf-8"
    )
    env = {**os.environ, "BROWSER": f"{sys.executable} {recorder} %s"}
    args = [str(entry_point()), "view", str(file), *(["--model", str(model)] if model else [])]
    started = time.monotonic()
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, text=True)
    try:
        while not address.exists() and time.monotonic() - started < 60:
            time.sleep(0.1)
        assert address.exists(), "mosaic view opened no page"
        run = subprocess.run(
            [
                bun,
                "viewer/scripts/browse.ts",
                "--url",
                address.read_text(encoding="utf-8"),
                query,
                node,
            ],
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
    assert proc.returncode == 0
    assert seen["errors"] == []
    return seen["named"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_built_viewer_carries_no_model_and_is_the_same_with_or_without_one(
    bun: str, tmp_path: Path
) -> None:
    """Answer A: the model is never bundled into the viewer build (so export may leave it out)."""
    dist = REPO / "viewer" / "dist"
    files = sorted(p for p in dist.rglob("*") if p.is_file())
    assert files and not [p for p in files if p.suffix == ".onnx" or sha(p) in PINNED]
    before = {p.relative_to(dist).as_posix(): sha(p) for p in files}
    walk(bun, tmp_path, READING / "mosaic.mosaic", "Item", "Item:a", MODEL)
    after = {p.relative_to(dist).as_posix(): sha(p) for p in sorted(dist.rglob("*")) if p.is_file()}
    assert after == before, "mosaic view changed the built viewer"


def test_a_mosaic_of_another_model_opens_with_the_real_model_and_searches_by_names_and_text(
    bun: str, tmp_path: Path
) -> None:
    """Section 3.8: unsupported vectors still open; the fallback is names and full text."""
    file = tmp_path / "m.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", file)
    with_model = walk(bun, tmp_path, file, "Item", "Item:a", MODEL)
    without = walk(bun, tmp_path, file, "Item", "Item:a", None)
    assert with_model["banners"] == [] and without["banners"] == []
    assert {r["id"] for r in with_model["results"]} >= {"Item:a", "Item:b"}
    assert all(r["match"] != "vector" for r in with_model["results"])
    key = [(r["id"], r["match"]) for r in with_model["results"]]
    assert key == [(r["id"], r["match"]) for r in without["results"]]
    assert with_model["card"] == without["card"]
    assert with_model["header"] == without["header"]


def test_a_tessera_opens_with_the_real_model(bun: str, tmp_path: Path) -> None:
    file = tmp_path / "t.tessera"
    shutil.copyfile(READING / "tessera.tessera", file)
    seen = walk(bun, tmp_path, file, "Row", "Row:1", MODEL)
    assert seen["banners"] == []
    assert all(r["match"] != "vector" for r in seen["results"])


def test_a_mosaic_with_a_changed_vector_is_refused_by_the_command_with_the_real_model(
    tmp_path: Path,
) -> None:
    run = subprocess.run(
        [str(entry_point()), "view", str(READING / "vector-changed.mosaic"), "--model", str(MODEL)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "BROWSER": "false"},
    )
    assert run.returncode == 1
    assert "vector" in run.stderr and "vector-changed.mosaic" in run.stderr
    assert run.stdout == ""


def test_the_real_model_directory_is_accepted_as_fetched_and_left_unchanged(tmp_path: Path) -> None:
    """The directory `scripts/fetch_model.py` makes passes the pinned hashes as it is."""
    before = {
        p.relative_to(MODEL).as_posix(): (sha(p), p.stat().st_mtime_ns)
        for p in sorted(MODEL.rglob("*"))
        if p.is_file()
    }
    assert {h for h, _ in before.values()} >= PINNED
    address = tmp_path / "address.txt"
    recorder = tmp_path / "browser.py"
    recorder.write_text(
        f"import sys; open({str(address)!r}, 'w').write(sys.argv[1])\n", encoding="utf-8"
    )
    env = {**os.environ, "BROWSER": f"{sys.executable} {recorder} %s"}
    proc = subprocess.Popen(
        [str(entry_point()), "view", str(READING / "mosaic.mosaic"), "--model", str(MODEL)],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        started = time.monotonic()
        while not address.exists() and time.monotonic() - started < 60:
            time.sleep(0.1)
        assert address.exists(), "mosaic view refused the fetched model"
    finally:
        proc.send_signal(signal.SIGINT)
        proc.communicate(timeout=30)
    assert proc.returncode == 0
    after = {
        p.relative_to(MODEL).as_posix(): (sha(p), p.stat().st_mtime_ns)
        for p in sorted(MODEL.rglob("*"))
        if p.is_file()
    }
    assert after == before
