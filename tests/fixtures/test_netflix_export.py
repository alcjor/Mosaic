"""The Netflix mosaic exported with ``search: text`` opens offline (plan M3.8).

docs/design.md, Implementation plan, Viewer: one HTML file "that opens offline with a
double-click"; View file: ``search: text`` "(a few MB)". The Netflix mosaic is built as in
``tests/fixtures/test_netflix_read.py``, exported with the fixture's view file set to ``search:
text``, and opened from ``file://`` in Chromium with networking blocked: a name search and a
full-text search find Breaking Bad, its node page and the Title table. The export's size is
printed for the PR.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from mosaic_build.cli import main

from tests.conftest import REPO
from tests.fixtures.test_netflix_read import TITLE, Run, built  # noqa: F401 (the module's fixture)

pytestmark = pytest.mark.slow

VIEW = REPO / "conformance" / "fixtures" / "netflix" / "view.yaml"


def test_the_netflix_export_opens_offline_and_finds_a_title(
    built: tuple[Path, Run],  # noqa: F811
    tmp_path: Path,
) -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    assert subprocess.run([bun, "run", "build"], cwd=REPO / "viewer", check=False).returncode == 0
    mosaic, _ = built
    view = tmp_path / "view.yaml"
    text = VIEW.read_text(encoding="utf-8")
    assert "search: semantic\n" in text
    view.write_text(text.replace("search: semantic\n", "search: text\n"), encoding="utf-8")
    page = tmp_path / "netflix.html"
    assert main(["export", str(mosaic), "--view", str(view), "-o", str(page)]) == 0
    run = subprocess.run(
        [
            bun,
            "viewer/scripts/open-export.ts",
            str(page),
            "Breaking Bad",
            TITLE,
            "Title",
            "chemistry teacher",
            TITLE,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout.strip().splitlines()[-1])
    size = page.stat().st_size
    print(
        f"\nnetflix export (search: text): {size:,} bytes from a "
        f"{mosaic.stat().st_size:,}-byte mosaic; ready in {seen['readyMs']} ms"
    )
    assert seen["blocked"] == [] and seen["errors"] == [] and seen["alerts"] == []
    assert "Read-only export" in seen["header"]
    assert any(r["id"] == TITLE for r in seen["results"])
    assert str(seen["card"]).startswith("Breaking Bad")
    assert any(r["id"] == TITLE and r["match"] == "text" for r in seen["textResults"])
    assert len(seen["rows"]) == 20
    assert seen["mode"] == "text"
