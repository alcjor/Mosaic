"""The viewer opens a mosaic with the kit running in the page, searches it and shows node pages.

M2.9 (docs/design.md, First milestone: Viewer; Specification 0.1, sections 3.8, 8.1 and 8.2).
``viewer/scripts/browse.ts`` serves the built viewer and the mosaic as static files, with no
query server, and drives the page in Chromium: it types a query in the search box, opens a
result's node page, then the first of its links. The mosaic is the conforming one of
``conformance/reading/`` (invented data).
"""

import json
import re
import shutil
import subprocess

import pytest

from tests.conftest import REPO

MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"
STATIC = re.compile(r"GET /(|assets/[^/]+|mosaic\.mosaic)")
"""The only requests the page may make: itself, its built assets and the mosaic file."""


@pytest.mark.slow
def test_the_viewer_searches_and_opens_node_pages_with_the_kit_in_the_page() -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    build = subprocess.run(
        [bun, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run(
        [bun, "viewer/scripts/browse.ts", str(MOSAIC), "Item", "Item:a"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout.strip().splitlines()[-1])
    print(f"\nviewer in Chromium: opened, searched and showed a node in {seen['named_ms']} ms")
    assert seen["errors"] == []
    assert all(STATIC.fullmatch(r) for r in seen["requests"]), seen["requests"]
    assert "Open a mosaic" in seen["empty"]
    for how in ("named", "picked"):
        walk = seen[how]
        assert walk["header"][:1] == ["mosaic.mosaic"]
        assert re.fullmatch(r"[0-9a-f]{12}", walk["header"][1])
        ids = [r["id"] for r in walk["results"]]
        assert "Item:a" in ids and "Item:b" in ids
        for r in walk["results"]:
            assert r["match"] in {"exact", "text", "vector"}
            assert r["id"] in r["text"] and "Item" in r["text"]
        assert walk["card"].startswith("Item A")
        assert "Item:a" in walk["card"]
        assert walk["links"] == ["Group:x"]
        assert walk["sources"] and all(s.startswith("first/doc:") for s in walk["sources"])
        assert walk["opened"] == "Group:x"
        assert walk["hash"] == "#q=Item&node=Group%3Ax"
