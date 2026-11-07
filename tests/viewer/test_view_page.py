"""``mosaic view`` opens the viewer page with the mosaic loaded, in a real browser (M2.11).

docs/design.md (Implementation plan: Viewer, "``mosaic view`` opens the page with a mosaic
loaded, no query server"). The test builds the viewer, runs the installed ``mosaic view`` with
a browser that only records the address, then drives that address in Chromium with
``viewer/scripts/browse.ts --url``. The page names the file, searches it and opens a node with
the kit inside the page, and the file is unchanged afterwards.
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

import pytest

from tests.conftest import REPO
from tests.test_cli import entry_point

MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"


@pytest.mark.slow
def test_mosaic_view_opens_the_page_with_the_mosaic_loaded(tmp_path: Path) -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    build = subprocess.run(
        [bun, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert build.returncode == 0, build.stdout + build.stderr
    path = tmp_path / "loaded.mosaic"
    shutil.copyfile(MOSAIC, path)
    before = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    address = tmp_path / "address.txt"
    recorder = tmp_path / "browser.py"
    recorder.write_text(
        f"import sys; open({str(address)!r}, 'w').write(sys.argv[1])\n", encoding="utf-8"
    )
    env = {**os.environ, "BROWSER": f"{sys.executable} {recorder} %s"}
    started = time.monotonic()
    proc = subprocess.Popen(
        [str(entry_point()), "view", str(path)], env=env, stdout=subprocess.PIPE, text=True
    )
    try:
        while not address.exists() and time.monotonic() - started < 30:
            time.sleep(0.1)
        assert address.exists(), "mosaic view opened no page"
        url = address.read_text(encoding="utf-8")
        run = subprocess.run(
            [bun, "viewer/scripts/browse.ts", "--url", url, "Item", "Item:a"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    finally:
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=30)
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout.strip().splitlines()[-1])
    print(f"\nmosaic view in Chromium: {url}; header {seen['named']['header']}")
    assert proc.returncode == 0
    assert url in out
    assert seen["errors"] == []
    walk = seen["named"]
    assert walk["header"][0] == "loaded.mosaic"
    assert walk["header"][1] == "8adae50b32ad"
    assert {r["id"] for r in walk["results"]} >= {"Item:a", "Item:b"}
    assert walk["card"].startswith("Item A")
    assert walk["opened"] == "Group:x"
    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "address.txt",
        "browser.py",
        "loaded.mosaic",
    ]
