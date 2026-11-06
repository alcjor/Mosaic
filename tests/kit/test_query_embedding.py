"""The kit embeds queries with the model of section 6, in Bun and in a browser page (plan M2.8).

Specification 0.1, section 6 (model, tokenizer, query text, pooling, scoring), section 3.8 and
ADR-007 (kit with the model under 60 MB). The model files are fetched into ``.cache/model/`` (as
the builder's slow tests do). ``conformance/embedding/cases.json`` holds the builder's token
ids and signs for invented queries; these tests check that it is what the builder gives now,
then run the kit's tests on the real model (``kit/test/model/``) and embed every case inside a
Chromium page (``kit/scripts/query-in-page.ts``).
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from types import ModuleType

import pytest
from mosaic_build.mosaic import vectors as v

from tests.conftest import REPO

CASES = REPO / "conformance" / "embedding" / "cases.json"
AGREEMENT = 0.98
"""Plan M2.8: the kit's query vectors agree in sign with the builder's on 98 % of dimensions."""


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def embedder() -> v.Embedder:
    return v.Embedder(_load("fetch_model").fetch())


@pytest.mark.slow
def test_the_cases_are_what_the_builder_gives(embedder: v.Embedder) -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert cases["embed_model"] == v.EMBED_MODEL
    assert cases["max_tokens"] == v.MAX_TOKENS
    assert [c["query"] for c in cases["cases"]] == _load("make_embedding_cases").QUERIES
    for case in cases["cases"]:
        assert case["text"] == v.query_text(case["query"])
        assert case["ids"] == embedder.tokenizer.encode(case["text"]).ids
        assert case["bits"] == v.to_bits(embedder.query(case["query"])).hex()


@pytest.mark.slow
def test_the_kit_passes_its_tests_on_the_real_model(embedder: v.Embedder) -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to run the kit's tests (CLAUDE.md, Commands)"
    run = subprocess.run(
        [bun, "--bun", "vitest", "run", "--config", "vitest.model.config.ts", "--silent=false"],
        cwd=REPO / "kit",
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    marks = ("sign agreement:", "query embedding:", "kit with model:")
    report = [line for line in run.stdout.splitlines() if line.startswith(marks)]
    print("\n" + "\n".join(report))
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]


@pytest.mark.slow
def test_the_kit_embeds_queries_in_a_browser_page_like_the_builder(embedder: v.Embedder) -> None:
    bun = shutil.which("bun")
    assert bun, "bun is needed to bundle the kit (CLAUDE.md, Commands)"
    run = subprocess.run(
        [bun, "kit/scripts/query-in-page.ts"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.strip().splitlines()[-1])
    print(f"\nquery embedding in Chromium: {result}")
    assert result["tokens_equal"] is True
    assert result["texts"] == len(json.loads(CASES.read_text(encoding="utf-8"))["cases"])
    assert 1 - result["differing"] / result["dimensions"] >= AGREEMENT
