"""Edge cases for vectors in the builder with the real model (slow: it needs the model files).

Specification 0.1, sections 3.7, 6 (node text, truncation at 256 tokens, stored vector), 7
(same inputs, same vector hash). Texts of very different lengths are built in one mosaic, in two
input orders, so that whatever grouping the builder uses for the model changes between builds;
the vectors must not.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from mosaic_build.cli import main
from mosaic_build.mosaic import Built, build
from mosaic_build.mosaic import vectors as v
from mosaic_format.check import check_file
from mosaic_format.reader import open as open_sealed

from tests.conftest import REPO
from tests.mosaic.pieces import evidence, node, pattern, tessera
from tests.test_cli import imported, write_pattern

pytestmark = pytest.mark.slow

ITEM = {
    "Item": {
        "key": "code",
        "from": {"list.Row": {"code": "key", "label": "label", "summary": "summary"}},
    }
}


def _fetch() -> Path:
    path = REPO / "scripts" / "fetch_model.py"
    spec = importlib.util.spec_from_file_location("fetch_model_vectors_edges", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_model_vectors_edges"] = module
    spec.loader.exec_module(module)
    return module.fetch()


@pytest.fixture(scope="module")
def model_dir() -> Path:
    return _fetch()


def _inputs() -> tuple[list[Any], list[Any]]:
    """Sixty nodes: empty and one-word texts, medium ones, and ones past 256 tokens."""
    nodes: list[Any] = []
    evs: list[Any] = []
    for i in range(60):
        key = f"K{i:03d}"
        words = ("alpha beta gamma delta " * (i * 3)).strip()
        nodes.append(
            node(f"Row:{key}", key, label=None if i % 7 == 0 else f"Label {i}", summary=words)
        )
        evs.append(
            evidence(f"Row:{key}", f"row={i + 1}", snippet=("é ü ß " * (i % 5 * 40)) or None)
        )
    return nodes, evs


def _build(directory: Path, model: Path, *, reverse: bool = False) -> Built:
    directory.mkdir(parents=True)
    nodes, evs = _inputs()
    if reverse:
        nodes, evs = nodes[::-1], evs[::-1]
    path = directory / "list.tessera"
    h = tessera(path, nodes, evidence=evs)
    return build(
        pattern(directory, [f"list@{h}"], ITEM),
        "default",
        directory / "out.mosaic",
        pieces=[path],
        model=model,
    )


def _vectors(built: Built) -> dict[str, bytes]:
    with open_sealed(built.path) as f:
        rows = [
            tuple(r)
            for r in f.query(
                "SELECT n.id, v.bits FROM vector v JOIN node n USING (nid) ORDER BY nid"
            )
        ]
    found: dict[str, bytes] = {}
    for i, b in rows:
        assert isinstance(b, bytes)
        found[str(i)] = b
    return found


@pytest.fixture(scope="module")
def forward(model_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Built:
    return _build(tmp_path_factory.mktemp("edges") / "fwd", model_dir)


def test_the_input_order_does_not_change_the_vector_hash(
    forward: Built, model_dir: Path, tmp_path: Path
) -> None:
    # Section 7: the same inputs give the same vector hash. Reversing the nodes changes how a
    # builder would group texts of different lengths for the model.
    backward = _build(tmp_path / "bwd", model_dir, reverse=True)
    assert backward.knowledge_hash == forward.knowledge_hash
    assert backward.vector_hash == forward.vector_hash
    assert _vectors(backward) == _vectors(forward)


def test_texts_of_every_length_are_embedded_as_the_model_embeds_each_on_its_own(
    forward: Built, model_dir: Path
) -> None:
    # Section 6: the stored vector is the signs of the node's own embedding, whatever else is in
    # the build (a longer text in the same group must not change a shorter one).
    embedder = v.Embedder(model_dir)
    nodes, evs = _inputs()
    snippets = {e.subject: e.snippet for e in evs}
    expected = {
        f"Item:{n.key}": embedder.bits(
            v.node_text("Item", n.key, n.label, n.summary, snippets[n.id])
        )
        for n in nodes
    }
    assert _vectors(forward) == expected


def test_the_texts_past_256_tokens_are_in_the_build_and_still_distinct_before_the_cut(
    forward: Built,
) -> None:
    vectors = _vectors(forward)
    assert len(vectors) == 60 and all(len(b) == 48 for b in vectors.values())
    assert len(set(vectors.values())) > 50


def test_the_vector_hash_is_the_hash_of_the_bits_in_nid_order(forward: Built) -> None:
    joined = b"".join(_vectors(forward).values())
    assert forward.vector_hash == hashlib.sha256(joined).hexdigest()
    report = check_file(forward.path, pieces=[forward.path.parent / "list.tessera"])
    assert report.ok, report.violations


def test_a_node_with_nothing_but_a_key_gets_the_vector_of_its_bare_text(
    model_dir: Path, tmp_path: Path
) -> None:
    tmp_path.mkdir(exist_ok=True)
    path = tmp_path / "list.tessera"
    h = tessera(path, [node("Row:x", "x")])
    built = build(
        pattern(tmp_path, [f"list@{h}"], ITEM),
        "default",
        tmp_path / "out.mosaic",
        pieces=[path],
        model=model_dir,
    )
    assert _vectors(built) == {"Item:x": v.Embedder(model_dir).bits("Item x: .  ")}


def test_the_command_line_builds_and_checks_a_mosaic_with_the_real_model(
    model_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Section 7.2: the build report has the vector hash; the message "vectors skipped" is gone.
    _, piece_hash = imported(tmp_path)
    pattern_path = write_pattern(tmp_path, piece_hash)
    args = ["build", str(pattern_path), "--pieces", str(tmp_path / "pieces")]
    out = tmp_path / "out"
    assert main([*args, "--model", str(model_dir), "-o", str(out)]) == 0
    seen = capsys.readouterr()
    assert "skipped" not in seen.err + seen.out
    mosaic = out / "default.mosaic"
    with open_sealed(mosaic) as f:
        ((vector_hash, embed_model),) = f.query("SELECT vector_hash, embed_model FROM header")
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    assert report["vector_hash"] == vector_hash and embed_model == v.EMBED_MODEL
    assert main(["check", str(mosaic), "--pieces", str(tmp_path / "pieces")]) == 0
