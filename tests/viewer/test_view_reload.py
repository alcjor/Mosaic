"""``mosaic view FILE --view VIEW`` reshapes the open page when the view file is saved (M3.7).

docs/design.md, Implementation plan, "View file": "Edited in your own editor; mosaic view watches
it and reloads the page on save". The test builds the viewer, runs the installed ``mosaic view``
with a view file and a browser that only records the address, then drives that address in
Chromium with ``viewer/scripts/watch-view.ts``: it saves a changed view file while the page is
open, and the page is shaped by it without restarting the command or reloading the page; then it
saves the file with an error, and the page keeps what it shows and shows the error.
"""

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
FIRST = "theme: light\ntypes:\n  Item:\n    label: Thing\n"
NEXT = "theme: dark\ntypes:\n  Group:\n    label: Team\n  Item: {}\n"
BROKEN = "theme: sepia\ntypes:\n  Item: {}\n"


@pytest.mark.slow
def test_a_saved_view_file_reshapes_the_open_page_and_an_error_keeps_it(tmp_path: Path) -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    build = subprocess.run(
        [bun, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert build.returncode == 0, build.stdout + build.stderr
    path = tmp_path / "loaded.mosaic"
    shutil.copyfile(MOSAIC, path)
    view = tmp_path / "view.yaml"
    view.write_text(FIRST, encoding="utf-8")
    (tmp_path / "next.yaml").write_text(NEXT, encoding="utf-8")
    (tmp_path / "broken.yaml").write_text(BROKEN, encoding="utf-8")
    address = tmp_path / "address.txt"
    recorder = tmp_path / "browser.py"
    recorder.write_text(
        f"import sys; open({str(address)!r}, 'w').write(sys.argv[1])\n", encoding="utf-8"
    )
    env = {**os.environ, "BROWSER": f"{sys.executable} {recorder} %s"}
    started = time.monotonic()
    proc = subprocess.Popen(
        [str(entry_point()), "view", str(path), "--view", str(view)],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        while not address.exists() and time.monotonic() - started < 30:
            time.sleep(0.1)
        assert address.exists(), "mosaic view opened no page"
        url = address.read_text(encoding="utf-8")
        run = subprocess.run(
            [
                bun,
                "viewer/scripts/watch-view.ts",
                "--url",
                url,
                "--view",
                str(view),
                "--next",
                str(tmp_path / "next.yaml"),
                "--broken",
                str(tmp_path / "broken.yaml"),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        still_running = proc.poll() is None
    finally:
        proc.send_signal(signal.SIGINT)
        proc.communicate(timeout=30)
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout.strip().splitlines()[-1])
    print(f"\nreshaped {seen['reshapedMs']} ms after the save; error shown: {seen['error']}")
    assert still_running, "mosaic view stopped while the view file was saved"
    assert seen["errors"] == []
    assert [t["type"] for t in seen["first"]] == ["Item"]
    assert seen["first"][0]["text"].startswith("Thing")
    assert seen["firstTheme"] == "light"
    assert [t["type"] for t in seen["second"]] == ["Group", "Item"]
    assert seen["second"][0]["text"].startswith("Team")
    assert seen["secondTheme"] == "dark"
    assert seen["loads"] == 1, "the page was reloaded instead of reshaped"
    assert f"{view}:1: view file: theme" in seen["error"]
    assert seen["third"] == seen["second"]
    assert seen["thirdTheme"] == "dark"
    assert proc.returncode == 0
