"""Vectors in the builder with the real model of section 6 (slow: it needs the model files).

``scripts/fetch_model.py`` fetches the files and checks them by their pinned hashes. A build
with the model directory gives each node the bits of its node text as the model embeds it on
its own (sections 3.7 and 6); two builds of the same inputs give the same vector hash (section
7); the mosaic passes the checker (section 3.9, invariant 14).
"""

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from mosaic_build.mosaic import Built, build
from mosaic_build.mosaic import vectors as v
from mosaic_format.check import check_file
from mosaic_format.reader import open as open_sealed

from tests.conftest import REPO
from tests.mosaic.pieces import evidence, node, pattern, tessera

pytestmark = pytest.mark.slow

ITEM = {
    "Item": {
        "key": "code",
        "from": {"list.Row": {"code": "key", "label": "label", "summary": "summary"}},
    }
}
NODES = [
    node("Row:P-1", "P-1", label="Feed pump", summary="Moves water from the tank to the boiler."),
    node("Row:V-2", "V-2", label="Relief valve", summary="Opens above the set pressure."),
    node("Row:T-3", "T-3", label="Storage tank"),
    node("Row:Ω", "Ω", summary="A node keyed by a non-ASCII letter."),
]
EVIDENCE = [
    evidence("Row:P-1", "row=1", snippet="P-1,Feed pump,water"),
    evidence("Row:V-2", "row=2", snippet="V-2,Relief valve"),
    evidence("Row:T-3", "row=3"),
    evidence("Row:Ω", "row=4", snippet="Ω," + "long text " * 120),
]


def _fetch() -> Path:
    path = REPO / "scripts" / "fetch_model.py"
    spec = importlib.util.spec_from_file_location("fetch_model_vectors", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_model_vectors"] = module
    spec.loader.exec_module(module)
    return module.fetch()


@pytest.fixture(scope="module")
def model_dir() -> Path:
    return _fetch()


def _build(directory: Path, model: Path) -> Built:
    directory.mkdir()
    path = directory / "list.tessera"
    h = tessera(path, NODES, evidence=EVIDENCE)
    return build(
        pattern(directory, [f"list@{h}"], ITEM),
        "default",
        directory / "out.mosaic",
        pieces=[path],
        model=model,
    )


def _rows(built: Built, sql: str) -> list[tuple[Any, ...]]:
    with open_sealed(built.path) as f:
        return [tuple(r) for r in f.query(sql)]


@pytest.fixture(scope="module")
def built(model_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Built:
    return _build(tmp_path_factory.mktemp("vectors") / "one", model_dir)


def test_each_vector_is_the_bits_of_the_node_text(built: Built, model_dir: Path) -> None:
    embedder = v.Embedder(model_dir)
    found = dict(_rows(built, "SELECT n.id, v.bits FROM vector v JOIN node n USING (nid)"))
    snippets = {e.subject: e.snippet for e in EVIDENCE}
    expected = {
        f"Item:{n.key}": embedder.bits(
            v.node_text("Item", n.key, n.label, n.summary, snippets[n.id])
        )
        for n in NODES
    }
    assert found == expected
    assert len(set(expected.values())) == len(NODES)


def test_the_header_names_the_model_and_the_hash_of_the_bits(built: Built) -> None:
    ((vector_hash, embed_model),) = _rows(built, "SELECT vector_hash, embed_model FROM header")
    bits = b"".join(bytes(b) for (b,) in _rows(built, "SELECT bits FROM vector ORDER BY nid"))
    assert vector_hash == hashlib.sha256(bits).hexdigest() == built.vector_hash
    assert embed_model == v.EMBED_MODEL


def test_two_builds_give_the_same_vector_hash(
    built: Built, model_dir: Path, tmp_path: Path
) -> None:
    again = _build(tmp_path / "two", model_dir)
    assert again.vector_hash == built.vector_hash
    assert again.knowledge_hash == built.knowledge_hash


def test_the_mosaic_passes_the_checker(built: Built) -> None:
    report = check_file(built.path, pieces=[built.path.parent / "list.tessera"])
    assert report.ok, report.violations


def test_the_model_runs_on_the_cpu_in_one_thread(model_dir: Path) -> None:
    # ADR-005, option A: vectors are built on the CPU, in one thread.
    session = v.Embedder(model_dir)._session
    options = session.get_session_options()
    assert session.get_providers() == ["CPUExecutionProvider"]
    assert (options.intra_op_num_threads, options.inter_op_num_threads) == (1, 1)
