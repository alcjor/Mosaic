"""Vectors in the builder (Specification 0.1, sections 3.3, 3.7, 6, 7, 7.1 step 7, 7.2, 3.9).

A target with ``vectors: true`` (the default, section 5.4) gets one 48-byte vector per node,
made from the node text of section 6; its header names ``embed_model`` and the vector hash, and
the build report the vector hash. ``vectors: false`` gets no vectors, with both header fields
NULL. The knowledge hash does not cover vectors (section 3.6), and the same inputs give the same
vector hash (section 7).

These tests run without the model files: :class:`tests.mosaic.pieces.StubModel` stands in for
the model, so they check which text each node is embedded from and where the bits go. The slow
tests in ``test_build_vectors_model.py`` run the real model.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from mosaic_build.mosaic import REPORT, BuildError, Built, build
from mosaic_build.mosaic import vectors as v
from mosaic_format.check import check_file
from mosaic_format.reader import open as open_sealed

from tests.mosaic.pieces import StubModel, evidence, node, pattern, stub_bits, tessera

ROW = {"Row": {"key": "k", "from": {"list.Row": {"k": "key"}}}}
LABELLED = {
    "Item": {
        "key": "code",
        "from": {"list.Row": {"code": "key", "label": "label", "summary": "summary"}},
    }
}


def _build(
    directory: Path,
    nodes: list[Any],
    types: dict[str, Any],
    *,
    mosaics: dict[str, Any] | None = None,
    target: str = "default",
    model: Any = None,
    **piece: Any,
) -> Built:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "list.tessera"
    if not path.exists():
        tessera(path, nodes, **piece)
    with open_sealed(path) as f:
        listed = [f"list@{f.knowledge_hash}"]
    return build(
        pattern(directory, listed, types, mosaics=mosaics),
        target,
        directory / "out.mosaic",
        pieces=[path],
        model=StubModel() if model is None else model,
    )


def _rows(built: Built, sql: str) -> list[tuple[Any, ...]]:
    with open_sealed(built.path) as f:
        return [tuple(r) for r in f.query(sql)]


def _header(built: Built) -> tuple[Any, Any]:
    ((vector_hash, embed_model),) = _rows(built, "SELECT vector_hash, embed_model FROM header")
    return vector_hash, embed_model


def _report(built: Built) -> dict[str, Any]:
    assert built.report is not None
    return json.loads(built.report.read_text(encoding="utf-8"))


def _vectors(built: Built) -> dict[str, bytes]:
    rows = _rows(built, "SELECT n.id, v.bits FROM vector v JOIN node n USING (nid) ORDER BY nid")
    return {str(i): bytes(b) for i, b in rows}


THREE = [node("Row:b", "b"), node("Row:a", "a"), node("Row:c", "c")]


# --- vectors on ---------------------------------------------------------------------------------


def test_vectors_on_gives_one_48_byte_vector_per_node(tmp_path: Path) -> None:
    built = _build(tmp_path, THREE, ROW)
    vectors = _vectors(built)
    assert list(vectors) == ["Row:a", "Row:b", "Row:c"]
    assert all(len(bits) == 48 for bits in vectors.values())
    ((nodes,),) = _rows(built, "SELECT count(*) FROM node")
    assert nodes == 3


def test_the_header_names_the_model_and_the_vector_hash(tmp_path: Path) -> None:
    built = _build(tmp_path, THREE, ROW)
    vector_hash, embed_model = _header(built)
    assert embed_model == (
        "snowflake-arctic-embed-xs@e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
    )
    bits = b"".join(bytes(b) for (b,) in _rows(built, "SELECT bits FROM vector ORDER BY nid"))
    assert vector_hash == hashlib.sha256(bits).hexdigest()
    assert built.vector_hash == vector_hash


def test_the_build_report_has_the_vector_hash(tmp_path: Path) -> None:
    built = _build(tmp_path, THREE, ROW)
    report = _report(built)
    assert report["vector_hash"] == _header(built)[0]
    assert report["knowledge_hash"] == built.knowledge_hash


def test_the_vectors_skipped_message_is_gone(tmp_path: Path) -> None:
    built = _build(tmp_path, THREE, ROW)
    assert built.messages == ()
    assert not any("skipped" in m for m in built.messages)


def test_each_node_is_embedded_from_its_node_text(tmp_path: Path) -> None:
    # Section 6: `<type> <key>: <label>. <summary> <snippet>`, with the mosaic's type and key.
    nodes = [node("Row:T-1", "T-1", label="Gauge one", summary="Reads the tank.")]
    ev = [evidence("Row:T-1", "row=1", snippet="T-1,Gauge one")]
    built = _build(tmp_path, nodes, LABELLED, evidence=ev)
    text = "Item T-1: Gauge one. Reads the tank. T-1,Gauge one"
    assert _vectors(built) == {"Item:T-1": stub_bits(text)}


def test_a_node_without_label_summary_or_snippet_embeds_empty_strings(tmp_path: Path) -> None:
    built = _build(tmp_path, [node("Row:a", "a")], ROW)
    assert _vectors(built) == {"Row:a": stub_bits("Row a: .  ")}


def test_the_snippet_is_the_first_in_evid_order_and_cut_at_800(tmp_path: Path) -> None:
    # Locators rank evidence of one node from one source (section 3.6): "row=1" before "row=2".
    long = "é" * 900
    ev = [
        evidence("Row:a", "row=2", snippet="second"),
        evidence("Row:a", "row=1", snippet=long),
    ]
    built = _build(tmp_path, [node("Row:a", "a")], ROW, evidence=ev)
    assert _vectors(built) == {"Row:a": stub_bits("Row a: .  " + "é" * 800)}


def test_a_snippet_the_text_tier_drops_is_not_embedded(tmp_path: Path) -> None:
    ev = [evidence("Row:a", "row=1", snippet="kept only with snippets")]
    built = _build(
        tmp_path,
        [node("Row:a", "a")],
        ROW,
        mosaics={"bare": {"text": "none"}},
        target="bare",
        evidence=ev,
    )
    assert _vectors(built) == {"Row:a": stub_bits("Row a: .  ")}


def test_each_node_is_embedded_once(tmp_path: Path) -> None:
    model = StubModel()
    _build(tmp_path, THREE, ROW, model=model)
    assert sorted(model.texts) == ["Row a: .  ", "Row b: .  ", "Row c: .  "]


def test_a_mosaic_with_vectors_passes_the_checker(tmp_path: Path) -> None:
    built = _build(tmp_path, THREE, ROW)
    report = check_file(built.path, pieces=[tmp_path / "list.tessera"])
    assert report.ok, report.violations


def test_a_mosaic_left_with_no_nodes_has_no_vectors_and_both_fields_null(tmp_path: Path) -> None:
    # Section 3.3: the fields are set for a "mosaic with vectors"; one with no nodes has none
    # (section 3.7: one row per node), so both are NULL. Trust `reviewed` drops the only node.
    ev = [evidence("Row:a", "row=1", method="inferred", confidence=0.5)]
    built = _build(tmp_path, [node("Row:a", "a")], ROW, evidence=ev)
    assert _rows(built, "SELECT count(*) FROM node") == [(0,)]
    assert _vectors(built) == {}
    assert _header(built) == (None, None)
    assert _report(built)["vector_hash"] is None


# --- vectors off ---------------------------------------------------------------------------------


def test_vectors_off_gives_no_vectors_and_both_header_fields_null(tmp_path: Path) -> None:
    model = StubModel()
    built = _build(
        tmp_path, THREE, ROW, mosaics={"plain": {"vectors": False}}, target="plain", model=model
    )
    assert _vectors(built) == {}
    assert _header(built) == (None, None)
    assert built.vector_hash is None
    assert _report(built)["vector_hash"] is None
    assert model.texts == []


def test_vectors_off_needs_no_model(tmp_path: Path) -> None:
    directory = tmp_path / "d"
    directory.mkdir()
    path = directory / "list.tessera"
    h = tessera(path, THREE)
    built = build(
        pattern(directory, [f"list@{h}"], ROW, mosaics={"plain": {"vectors": False}}),
        "plain",
        directory / "out.mosaic",
        pieces=[path],
    )
    assert _header(built) == (None, None)


# --- determinism ---------------------------------------------------------------------------------


def test_the_knowledge_hash_is_the_same_with_vectors_on_and_off(tmp_path: Path) -> None:
    ev = [evidence("Row:a", "row=1", snippet="x")]
    mosaics = {"on": {"vectors": True}, "off": {"vectors": False}}
    on = _build(tmp_path / "on", THREE, ROW, mosaics=mosaics, target="on", evidence=ev)
    off = _build(tmp_path / "off", THREE, ROW, mosaics=mosaics, target="off", evidence=ev)
    assert on.knowledge_hash == off.knowledge_hash
    assert (on.vector_hash is None, off.vector_hash is None) == (False, True)


def test_two_builds_of_the_same_inputs_give_the_same_vector_hash(tmp_path: Path) -> None:
    first = _build(tmp_path / "one", THREE, ROW)
    second = _build(tmp_path / "two", list(reversed(THREE)), ROW)
    assert first.vector_hash == second.vector_hash
    assert _vectors(first) == _vectors(second)


# --- the model -----------------------------------------------------------------------------------


def _pieces(directory: Path, mosaics: dict[str, Any] | None = None) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "list.tessera"
    h = tessera(path, THREE)
    return pattern(directory, [f"list@{h}"], ROW, mosaics=mosaics), path


def _failed(directory: Path) -> dict[str, Any]:
    return json.loads((directory / REPORT).read_text(encoding="utf-8"))


def test_vectors_on_without_a_model_fails_with_invalid_input(tmp_path: Path) -> None:
    pattern_path, piece = _pieces(tmp_path)
    with pytest.raises(BuildError) as raised:
        build(pattern_path, "default", tmp_path / "out.mosaic", pieces=[piece])
    assert raised.value.reason == "invalid_input"
    assert "vectors" in str(raised.value) and "model" in str(raised.value)
    assert not (tmp_path / "out.mosaic").exists()
    report = _failed(tmp_path)
    assert (report["outcome"], report["reason"]) == ("failed", "invalid_input")
    assert (report["knowledge_hash"], report["vector_hash"], report["file_size"]) == (None,) * 3


def test_a_model_directory_without_the_files_fails_naming_the_file(tmp_path: Path) -> None:
    pattern_path, piece = _pieces(tmp_path / "p")
    empty = tmp_path / "model"
    empty.mkdir()
    with pytest.raises(BuildError) as raised:
        build(pattern_path, "default", tmp_path / "out.mosaic", pieces=[piece], model=empty)
    assert raised.value.reason == "invalid_input"
    assert "onnx/model_quantized.onnx" in str(raised.value)
    assert not (tmp_path / "out.mosaic").exists()
    assert _failed(tmp_path)["reason"] == "invalid_input"


def test_a_model_file_with_another_hash_fails_naming_both_hashes(tmp_path: Path) -> None:
    pattern_path, piece = _pieces(tmp_path / "p")
    model = tmp_path / "model"
    (model / "onnx").mkdir(parents=True)
    (model / "onnx" / "model_quantized.onnx").write_bytes(b"not the model")
    (model / "tokenizer.json").write_bytes(b"{}")
    with pytest.raises(BuildError) as raised:
        build(pattern_path, "default", tmp_path / "out.mosaic", pieces=[piece], model=model)
    message = str(raised.value)
    assert raised.value.reason == "invalid_input"
    assert hashlib.sha256(b"not the model").hexdigest() in message
    assert v.MODEL.model_file.sha256 in message


def test_vectors_off_ignores_a_broken_model_directory(tmp_path: Path) -> None:
    pattern_path, piece = _pieces(tmp_path / "p", mosaics={"plain": {"vectors": False}})
    empty = tmp_path / "model"
    empty.mkdir()
    built = build(pattern_path, "plain", tmp_path / "out.mosaic", pieces=[piece], model=empty)
    assert _header(built) == (None, None)


def test_an_over_budget_report_gives_the_removed_files_vector_hash(tmp_path: Path) -> None:
    # Section 7.3: an over-budget report gives the removed file's hashes and file_size.
    with pytest.raises(BuildError) as raised:
        _build(tmp_path, THREE, ROW, mosaics={"tiny": {"budget": "1 KB"}}, target="tiny")
    assert raised.value.reason == "over_budget"
    report = _failed(tmp_path)
    bits = b"".join(stub_bits(f"Row {k}: .  ") for k in "abc")
    assert report["vector_hash"] == hashlib.sha256(bits).hexdigest()
    assert not (tmp_path / "out.mosaic").exists()


def test_the_model_files_are_not_written_to(tmp_path: Path) -> None:
    # Principle 8 for the model as for sources: a failed check changes nothing in its directory.
    pattern_path, piece = _pieces(tmp_path / "p")
    model = tmp_path / "model"
    (model / "onnx").mkdir(parents=True)
    (model / "onnx" / "model_quantized.onnx").write_bytes(b"x")
    before = sorted(p.relative_to(model) for p in model.rglob("*"))
    with pytest.raises(BuildError):
        build(pattern_path, "default", tmp_path / "out.mosaic", pieces=[piece], model=model)
    assert sorted(p.relative_to(model) for p in model.rglob("*")) == before
    shutil.rmtree(model)
