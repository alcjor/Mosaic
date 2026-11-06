"""The kit opens a 10,000-node mosaic, both hashes checked, in under 3 s in a browser.

Specification 0.1, section 3.8 step 3 (hashes recomputed on every open); ADR-007 (open time).
The mosaic is invented: 10,000 items in 100 groups, each with two evidence rows, a snippet,
an alias and a vector. ``kit/scripts/open-time.ts`` bundles the kit for the browser, opens the
file in Chromium and prints the times; the kit's header must give mosaic_format's hashes.
"""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from mosaic_format import seal
from mosaic_format.hashes import knowledge_hash, vector_hash
from mosaic_format.writer import (
    Alias,
    Content,
    Edge,
    EdgeKey,
    Evidence,
    Header,
    Node,
    Source,
    Type,
    Vector,
)

from tests.conftest import REPO

NODES = 10_000
GROUPS = 100
BUDGET_MS = 3_000
"""ADR-007: opening a mosaic, hash checks included, takes under 3 s in a browser."""

PRODUCER = "open-time/0.1"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content(nodes: int = NODES) -> Content:
    """An invented mosaic of ``nodes`` nodes: items and the groups they belong to."""
    groups = [
        Node(id=f"Group:g{g:03}", type="Group", key=f"g{g:03}", label=f"Group {g}")
        for g in range(GROUPS)
    ]
    items = [
        Node(
            id=f"Item:i{i:05}",
            type="Item",
            key=f"i{i:05}",
            label=f"Item number {i}",
            summary=f"An invented item, number {i}, of group {i % GROUPS}.",
            props=json.dumps({"code": f"i{i:05}", "size": i}, separators=(",", ":")),
        )
        for i in range(nodes - GROUPS)
    ]
    edges = [
        Edge(type="in_group", src=n.id, dst=groups[i % GROUPS].id) for i, n in enumerate(items)
    ]
    evidence = [
        Evidence(
            n.id, "doc", f"row={i + 1}", "extracted", PRODUCER, snippet=f"{n.key}," + "x" * 160
        )
        for i, n in enumerate(items)
    ]
    evidence += [
        Evidence(n.id, "doc", f"row={i + 1};field=size", "inferred", "guess/1", "size", 0.75)
        for i, n in enumerate(items)
    ]
    evidence += [
        Evidence(g.id, "doc", f"group={g.key}", "extracted", PRODUCER, snippet=g.key)
        for g in groups
    ]
    evidence += [
        Evidence(
            EdgeKey(e.src, e.type, e.dst), "doc", f"row={i + 1};field=group", "extracted", PRODUCER
        )
        for i, e in enumerate(edges)
    ]
    every = [*groups, *items]
    return Content(
        header=Header(
            kind="mosaic",
            producer=PRODUCER,
            pattern_hash=_hash("pattern.yaml"),
            target="all",
            embed_model="invented-model@" + _hash("model file"),
        ),
        sources=[
            Source(
                id="doc", kind="file", hash=_hash("items.csv"), path="items.csv", notice="CC0-1.0"
            )
        ],
        types=[
            Type(
                name="Item", kind="node", key_prop="code", props='{"code":"text","size":"integer"}'
            ),
            Type(name="Group", kind="node"),
            Type(name="in_group", kind="edge", from_type="Item", to_type="Group"),
        ],
        nodes=every,
        edges=edges,
        aliases=[Alias(f"alias {n.key}", n.id, "source") for n in items],
        evidence=evidence,
        vectors=[Vector(n.id, hashlib.sha384(n.id.encode()).digest()) for n in every],
    )


@pytest.mark.slow
def test_the_kit_opens_a_10000_node_mosaic_in_a_browser_in_under_3_s(tmp_path: Path) -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to bundle the kit (CLAUDE.md, Commands)"
    path = tmp_path / "open-time.mosaic"
    sealed = seal(path, content())
    with sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True) as con:
        assert con.execute("SELECT count(*) FROM node").fetchone() == (NODES,)
        expected = (knowledge_hash(con), vector_hash(con))
    run = subprocess.run(
        [bun, "kit/scripts/open-time.ts", str(path), "--runs", "5"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.strip().splitlines()[-1])
    print(
        f"\nkit open in Chromium: {NODES:,} nodes, {result['bytes']:,} bytes; "
        f"runs {result['runs_ms']} ms, median {result['median_ms']} ms; "
        f"knowledge {result['knowledge_hash']} vector {result['vector_hash']}"
    )
    assert (result["knowledge_hash"], result["vector_hash"]) == expected
    assert sealed.knowledge_hash == expected[0]
    assert result["median_ms"] < BUDGET_MS
    assert max(result["runs_ms"]) < BUDGET_MS
