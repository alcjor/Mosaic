"""A ``mosaic export`` opens offline from ``file://`` in a real browser (plan M3.8).

docs/design.md, Implementation plan, Viewer: one HTML file "that opens offline with a
double-click". The test builds the viewer, exports the conformance mosaic with a ``search: text``
view file, and opens the file from ``file://`` in Chromium with networking blocked
(``viewer/scripts/open-export.ts``): the kit opens the mosaic by the reading rules, and a name
search and a full-text search find a node, its node page and its type's table. The same export
with one byte of the mosaic changed is refused by the hash check when the page opens it.
"""

import base64
import gzip
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from mosaic_build.cli import main
from mosaic_format.reader import open as open_sealed

from tests.conftest import MODEL, REPO

MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"
VIEW = "search: text\ntypes:\n  Item:\n    label: Thing\n  Group: {}\n"


def built() -> str:
    bun = shutil.which("bun")
    assert bun, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    run = subprocess.run(
        [bun, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
    return bun


def opened(bun: str, page: Path, *args: str) -> dict[str, Any]:
    run = subprocess.run(
        [bun, "viewer/scripts/open-export.ts", str(page), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.mark.slow
def test_the_export_opens_offline_and_finds_a_node_its_page_and_its_table(tmp_path: Path) -> None:
    bun = built()
    view = tmp_path / "view.yaml"
    view.write_text(VIEW, encoding="utf-8")
    page = tmp_path / "mosaic.html"
    assert main(["export", str(MOSAIC), "--view", str(view), "-o", str(page)]) == 0
    seen = opened(bun, page, "Item B", "Item:b", "Item", "Second", "Item:b")
    print(f"\nexport: {page.stat().st_size:,} bytes, ready in {seen['readyMs']} ms")
    assert seen["blocked"] == [] and seen["errors"] == [] and seen["alerts"] == []
    header = seen["header"]
    assert header[:2] == ["mosaic.mosaic", "8adae50b32ad"]
    assert "Read-only export" in header
    assert any(r["id"] == "Item:b" for r in seen["results"])
    assert str(seen["card"]).startswith("Item B")
    assert seen["links"] == ["Group:x"]
    assert any(r["id"] == "Item:b" and r["match"] == "text" for r in seen["textResults"])
    assert seen["rows"] == ["Item:a", "Item:b"]
    assert seen["mode"] == "text"


@pytest.mark.slow
def test_an_export_whose_mosaic_was_changed_is_refused_when_the_page_opens_it(
    tmp_path: Path,
) -> None:
    bun = built()
    view = tmp_path / "view.yaml"
    view.write_text(VIEW, encoding="utf-8")
    page = tmp_path / "mosaic.html"
    assert main(["export", str(MOSAIC), "--view", str(view), "-o", str(page)]) == 0
    text = page.read_text(encoding="utf-8")
    found = re.search(r'"mosaic":"([A-Za-z0-9+/=]+)"', text)
    assert found
    data = bytearray(gzip.decompress(base64.b64decode(found.group(1))))
    at = bytes(data).find(b"Item B")  # a label, so only the knowledge hash can tell
    assert at > 0
    data[at + 5] = ord("C")
    changed = base64.b64encode(gzip.compress(bytes(data), mtime=0)).decode("ascii")
    page.write_text(text.replace(found.group(1), changed), encoding="utf-8")
    seen = opened(bun, page, "Item", "Item:b", "Item")
    assert seen["blocked"] == []
    alerts = " ".join(seen["alerts"])
    assert "mosaic.mosaic" in alerts and "hash" in alerts, alerts


CUT = "search: text\nexport:\n  types: [Item]\n"


@pytest.mark.slow
def test_a_cut_export_opens_offline_and_says_where_it_comes_from(tmp_path: Path) -> None:
    # Plan M3.10, answer on #140: the cut is built from the source mosaic as its one piece; the
    # page shows the cut's own checked hash and "from <source> <hash>" read from the file.
    bun = built()
    view = tmp_path / "view.yaml"
    view.write_text(CUT, encoding="utf-8")
    page = tmp_path / "cut.html"
    assert main(["export", str(MOSAIC), "--view", str(view), "-o", str(page)]) == 0
    seen = opened(bun, page, "Item A", "Item:a", "Item")
    assert seen["blocked"] == [] and seen["errors"] == [] and seen["alerts"] == []
    header = " ".join(seen["header"])
    print(f"\ncut export header: {header}")
    assert seen["header"][0] == "mosaic.mosaic"
    assert seen["header"][1] != "8adae50b32ad"  # the cut's own knowledge hash, checked on open
    assert "from mosaic 8adae50b32ad" in header
    assert seen["links"] == []  # Group is not carried, so neither is in_group
    assert seen["rows"] == ["Item:a", "Item:b"]


@pytest.mark.slow
def test_a_semantic_cut_carries_vectors_for_its_nodes(tmp_path: Path) -> None:
    built()
    view = tmp_path / "view.yaml"
    view.write_text("search: semantic\nexport:\n  types: [Item]\n", encoding="utf-8")
    page = tmp_path / "cut.html"
    args = ["export", str(MOSAIC), "--view", str(view), "--model", str(MODEL), "-o", str(page)]
    assert main(args) == 0
    found = re.search(r'"mosaic":"([A-Za-z0-9+/=]+)"', page.read_text(encoding="utf-8"))
    assert found
    path = tmp_path / "carried.mosaic"
    path.write_bytes(gzip.decompress(base64.b64decode(found.group(1))))
    with open_sealed(path) as sealed:
        assert sealed.vector_hash is not None
        vectors, nodes = (sealed.query(f"SELECT count(*) FROM {t}") for t in ("vector", "node"))
        assert vectors == nodes
