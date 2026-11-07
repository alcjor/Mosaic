"""Which types an export carries (plan M3.10; docs/design.md, View file).

The view file's ``export.types`` (M3.5, answer on #120) names the node types an export carries;
what it means beyond that is asked on this slice's PR. This file starts with what is settled:
with ``export.types`` absent, the export carries the mosaic as it is, byte for byte, so the page
shows the mosaic's own knowledge hash.
"""

import base64
import gzip
import json
import re
import shutil
from pathlib import Path

import pytest
from mosaic_build import view
from mosaic_build.cli import main

from tests.conftest import REPO

MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text(
        '<script type="module" crossorigin src="./assets/index-A.js"></script>\n'
        '<link rel="stylesheet" crossorigin href="./assets/index-B.css">\n',
        encoding="utf-8",
    )
    (directory / "assets" / "index-A.js").write_text("const page = 1;\n", encoding="utf-8")
    (directory / "assets" / "index-B.css").write_text("body {}\n", encoding="utf-8")
    (directory / "assets" / "sqlite3-C.wasm").write_bytes(b"\0asm")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def carried(page: Path) -> bytes:
    found = re.search(r'id="mosaic-export">(.*?)</script>', page.read_text(encoding="utf-8"))
    assert found
    return gzip.decompress(base64.b64decode(json.loads(found.group(1))["mosaic"]))


def test_without_export_types_the_export_carries_the_mosaic_as_it_is(
    tmp_path: Path, dist: Path
) -> None:
    source = tmp_path / "mosaic.mosaic"
    shutil.copyfile(MOSAIC, source)
    settings = tmp_path / "view.yaml"
    settings.write_text("search: text\ntypes:\n  Item: {}\n", encoding="utf-8")
    page = tmp_path / "out.html"
    assert main(["export", str(source), "--view", str(settings), "-o", str(page)]) == 0
    assert carried(page) == MOSAIC.read_bytes()
