"""The kit's tools answer within 3 times the native 100 ms in a browser, on a 10,000-node mosaic.

Specification 0.1, section 8.1; ADR-007 (tool latency: under 100 ms at the 95th percentile
native, within 3 times that in a browser, for ``find``, ``get``, ``neighbors``, ``cite`` and a
page of ``table``). The mosaic is the invented one of ``test_open_time``: 10,000 items in 100
groups. Its ``embed_model`` is not the kit's, so ``find`` uses names and full text (section 3.8);
the vector tier is timed with the model in M2.12. ``kit/scripts/tool-latency.ts`` bundles the
kit for the browser, opens the file in Chromium and times each call from the page.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from mosaic_format import seal

from tests.conftest import REPO
from tests.kit.test_open_time import NODES, content

BUDGET_MS = 300
"""ADR-007: 3 times the native 100 ms, at the 95th percentile."""

RUNS = 50

CALLS = {
    "find": {"query": "Item number 4242"},
    "get": {"id": "Item:i04242"},
    "neighbors": {"id": "Group:g042"},
    "cite": {"id": "Item:i04242"},
    "table": {
        "type": "Item",
        "where": [{"column": "code", "op": "contains", "value": "42"}],
        "order": [{"column": "size", "direction": "desc"}],
        "page": 2,
    },
}


@pytest.mark.slow
def test_the_kit_s_tools_answer_within_3_times_native_in_a_browser(tmp_path: Path) -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to bundle the kit (CLAUDE.md, Commands)"
    path = tmp_path / "tool-latency.mosaic"
    seal(path, content())
    calls = tmp_path / "calls.json"
    calls.write_text(json.dumps(CALLS), encoding="utf-8")
    run = subprocess.run(
        [bun, "kit/scripts/tool-latency.ts", str(path), str(calls), "--runs", str(RUNS)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.strip().splitlines()[-1])
    p95, median = result["p95_ms"], result["median_ms"]
    print(
        f"\nkit tools in Chromium: {NODES:,} nodes, {result['bytes']:,} bytes, {RUNS} runs each; "
        + "; ".join(f"{t} p95 {p95[t]} ms (median {median[t]} ms)" for t in CALLS)
    )
    answers = result["answers"]
    assert set(p95) == set(CALLS)
    for tool in CALLS:
        assert answers[tool]["tool"] == tool
        assert "data" in answers[tool], answers[tool]
    # Each call does real work: the item is found, the group's links and the page are full.
    assert answers["find"]["data"]["results"][0]["id"] == "Item:i04242"
    assert answers["neighbors"]["data"]["total"] == (NODES - 100) // 100
    table = answers["table"]["data"]
    assert table["columns"] == ["id", "code", "size"]
    assert len(table["rows"]) == 20 and table["total"] > 40
    for tool in CALLS:
        assert p95[tool] < BUDGET_MS, f"{tool}: p95 {p95[tool]} ms, budget {BUDGET_MS} ms"
