"""Edge cases for vectors in the builder (Specification 0.1, sections 3.3, 3.7, 5.4, 6, 7, 7.1).

Written from the spec's words, with the stub model of ``tests/mosaic/pieces.py``: scope, many
nodes, merged nodes, edge evidence, the text tier, the strict and over-budget reports, tampered
vectors, and the header's settings.
"""

import hashlib
import json
import shutil
import sqlite3
from os import PathLike
from pathlib import Path
from typing import Any

import pytest
from mosaic_build.mosaic import REPORT, BuildError, Built, build
from mosaic_format.check import check_file
from mosaic_format.reader import open as open_sealed
from mosaic_format.writer import Edge, EdgeKey

from tests.mosaic.pieces import StubModel, evidence, node, pattern, stub_bits, tessera

ROW = {"Row": {"key": "k", "from": {"list.Row": {"k": "key"}}}}
LABELLED = {
    "Item": {
        "key": "code",
        "from": {"list.Row": {"code": "key", "label": "label", "summary": "summary"}},
    }
}


def _rows(built: Built, sql: str) -> list[tuple[Any, ...]]:
    with open_sealed(built.path) as f:
        return [tuple(r) for r in f.query(sql)]


def _vectors(built: Built) -> dict[str, bytes]:
    rows = _rows(built, "SELECT n.id, v.bits FROM vector v JOIN node n USING (nid) ORDER BY nid")
    return {str(i): bytes(b) for i, b in rows}


def _one(
    directory: Path,
    nodes: list[Any],
    types: dict[str, Any],
    *,
    mosaics: dict[str, Any] | None = None,
    target: str = "default",
    model: Any = None,
    edges: dict[str, Any] | None = None,
    **piece: Any,
) -> Built:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "list.tessera"
    h = tessera(path, nodes, **piece)
    return build(
        pattern(directory, [f"list@{h}"], types, edges=edges, mosaics=mosaics),
        target,
        directory / "out.mosaic",
        pieces=[path],
        model=StubModel() if model is None else model,
    )


def _piece(directory: Path, name: str, label: str | None = None, snippet: str | None = None) -> str:
    """Seal ``<name>.tessera`` with node ``Row:a`` and its own source; return ``name@hash``."""
    ev = [evidence("Row:a", "row=1", source=f"{name}.csv", snippet=snippet)]
    h = tessera(
        directory / f"{name}.tessera",
        [node("Row:a", "a", label=label)],
        source=f"{name}.csv",
        source_hash=hashlib.sha256(name.encode()).hexdigest(),
        evidence=ev,
    )
    return f"{name}@{h}"


# --- scope (section 5.4 `types`, section 3.7 one row per node) ----------------------------------


def test_only_nodes_in_the_targets_scope_get_vectors(tmp_path: Path) -> None:
    # Section 5.4 `types` and section 3.7: one vector per node of the mosaic, not of the pieces.
    types = {
        "Keep": {"key": "k", "from": {"list.Row": {"k": "key"}}},
        "Drop": {"key": "k", "from": {"list.Other": {"k": "key"}}},
    }
    nodes = [node("Row:a", "a"), node("Other:z", "z")]
    model = StubModel()
    built = _one(
        tmp_path, nodes, types, mosaics={"k": {"types": ["Keep"]}}, target="k", model=model
    )
    assert _vectors(built) == {"Keep:a": stub_bits("Keep a: .  ")}
    assert model.texts == ["Keep a: .  "]
    assert built.vector_hash == hashlib.sha256(stub_bits("Keep a: .  ")).hexdigest()


def test_a_node_dropped_by_trust_has_no_vector_and_the_others_keep_theirs(tmp_path: Path) -> None:
    # Section 7.1 step 6 runs before step 7: the dropped node is not embedded.
    ev = [
        evidence("Row:a", "row=1"),
        evidence("Row:b", "row=2", method="inferred", confidence=0.5),
    ]
    model = StubModel()
    built = _one(tmp_path, [node("Row:a", "a"), node("Row:b", "b")], ROW, model=model, evidence=ev)
    assert _vectors(built) == {"Row:a": stub_bits("Row a: .  ")}
    assert built.vector_hash == hashlib.sha256(stub_bits("Row a: .  ")).hexdigest()
    assert model.texts == ["Row a: .  "]


def test_a_trust_all_target_embeds_the_node_the_reviewed_target_drops(tmp_path: Path) -> None:
    ev = [evidence("Row:b", "row=2", method="inferred", confidence=0.5)]
    built = _one(
        tmp_path,
        [node("Row:b", "b")],
        ROW,
        mosaics={"all": {"trust": "all"}},
        target="all",
        evidence=ev,
    )
    assert _vectors(built) == {"Row:b": stub_bits("Row b: .  ")}


# --- many nodes ---------------------------------------------------------------------------------


def test_many_nodes_each_get_their_own_vector_in_nid_order(tmp_path: Path) -> None:
    # More nodes than any batch a builder would use; the order of the input is not the nid order.
    keys = [f"n{(i * 7919) % 3001:05d}" for i in range(3001)]
    nodes = [node(f"Row:{k}", k, label=f"label {k}") for k in keys]
    model = StubModel()
    built = _one(tmp_path, nodes, LABELLED_ROW_LABEL, model=model)
    rows = _rows(built, "SELECT n.key, v.bits FROM vector v JOIN node n USING (nid) ORDER BY nid")
    assert [r[0] for r in rows] == sorted(keys, key=lambda s: s.encode())
    assert all(bytes(bits) == stub_bits(f"Item {k}: label {k}.  ") for k, bits in rows)
    assert len(model.texts) == 3001 and len(set(model.texts)) == 3001
    joined = b"".join(bytes(bits) for _, bits in rows)
    assert built.vector_hash == hashlib.sha256(joined).hexdigest()


LABELLED_ROW_LABEL = {
    "Item": {"key": "code", "from": {"list.Row": {"code": "key", "label": "label"}}},
}


def test_a_single_node_has_one_vector_and_the_hash_of_its_bits(tmp_path: Path) -> None:
    built = _one(tmp_path, [node("Row:only", "only")], ROW)
    bits = stub_bits("Row only: .  ")
    assert _vectors(built) == {"Row:only": bits}
    assert built.vector_hash == hashlib.sha256(bits).hexdigest()


def test_the_vector_hash_follows_nid_order_not_input_order(tmp_path: Path) -> None:
    # Section 3.7: the bits are concatenated in nid order, which is the byte order of the id.
    nodes = [node("Row:é", "é"), node("Row:z", "z"), node("Row:B", "B"), node("Row:a", "a")]
    built = _one(tmp_path, nodes, ROW)
    order = ["Row:B", "Row:a", "Row:z", "Row:é"]
    assert list(_vectors(built)) == order
    joined = b"".join(stub_bits(f"Row {i[4:]}: .  ") for i in order)
    assert built.vector_hash == hashlib.sha256(joined).hexdigest()


# --- text of the node (section 6) ---------------------------------------------------------------


def test_a_label_with_newlines_and_a_non_bmp_character_is_embedded_as_it_is(tmp_path: Path) -> None:
    label = "line one\nline two\t\U0001f600"
    built = _one(tmp_path, [node("Row:a", "a", label=label)], LABELLED_ROW_LABEL)
    assert _vectors(built) == {"Item:a": stub_bits(f"Item a: {label}.  ")}


def test_the_cut_of_the_snippet_counts_characters_outside_the_bmp(tmp_path: Path) -> None:
    ev = [evidence("Row:a", "row=1", snippet="\U0001f600" * 801)]
    built = _one(tmp_path, [node("Row:a", "a")], ROW, evidence=ev)
    assert _vectors(built) == {"Row:a": stub_bits("Row a: .  " + "\U0001f600" * 800)}


def test_the_text_uses_the_mosaics_type_not_the_pieces(tmp_path: Path) -> None:
    built = _one(tmp_path, [node("Row:a", "a")], {"Gauge": ROW["Row"]})
    assert list(_vectors(built)) == ["Gauge:a"]
    assert _vectors(built)["Gauge:a"] == stub_bits("Gauge a: .  ")


def test_a_snippet_on_an_edge_is_not_the_snippet_of_its_node(tmp_path: Path) -> None:
    # Section 6: the snippet is the node's. An edge's evidence belongs to the edge.
    types = {
        "Row": {"key": "k", "from": {"list.Row": {"k": "key"}}},
        "Unit": {"key": "k", "from": {"list.U": {"k": "key"}}},
    }
    edges = {"in": {"from": "Row", "to": "Unit", "map": ["list.in"]}}
    ev = [
        evidence("Row:a", "row=1"),
        evidence("U:v", "row=2"),
        evidence(EdgeKey("Row:a", "in", "U:v"), "edge=1", snippet="edge passage"),
    ]
    built = _with_edge(tmp_path, types, edges, ev)
    assert _vectors(built) == {
        "Row:a": stub_bits("Row a: .  "),
        "Unit:v": stub_bits("Unit v: .  "),
    }


def _with_edge(
    tmp_path: Path, types: dict[str, Any], edges: dict[str, Any], ev: list[Any]
) -> Built:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "list.tessera"
    h = tessera(
        path,
        [node("Row:a", "a"), node("U:v", "v")],
        edges=[Edge("in", "Row:a", "U:v")],
        evidence=ev,
    )
    return build(
        pattern(tmp_path, [f"list@{h}"], types, edges=edges),
        "default",
        tmp_path / "out.mosaic",
        pieces=[path],
        model=StubModel(),
    )


def test_the_snippet_of_a_merged_node_comes_from_the_first_piece_when_evidence_is_primary(
    tmp_path: Path,
) -> None:
    # Section 5.4: under `primary` the row of the highest-priority piece is the one kept, and
    # the node text takes the snippet of the evidence the mosaic holds.
    types = {
        "Row": {"key": "k", "from": {"p.Row": {"k": "key"}, "q.Row": {"k": "key"}}},
    }
    first = _piece(tmp_path, "p", snippet="from p")
    second = _piece(tmp_path, "q", snippet="from q")
    paths: list[str | PathLike[str]] = [tmp_path / "p.tessera", tmp_path / "q.tessera"]
    one = build(
        pattern(tmp_path, [first, second], types),
        "default",
        tmp_path / "one.mosaic",
        pieces=paths,
        model=StubModel(),
    )
    (tmp_path / "rev").mkdir()
    two = build(
        pattern(tmp_path / "rev", [second, first], types),
        "default",
        tmp_path / "rev" / "two.mosaic",
        pieces=paths,
        model=StubModel(),
    )
    assert _vectors(one) == {"Row:a": stub_bits("Row a: .  from p")}
    assert _vectors(two) == {"Row:a": stub_bits("Row a: .  from q")}
    assert len(_vectors(one)) == len(_vectors(two)) == 1


def test_the_label_of_a_merged_node_is_the_winning_one(tmp_path: Path) -> None:
    # Section 7.1 step 3: the earliest piece wins; one node, one vector, made from that label.
    types = {
        "Item": {
            "key": "k",
            "from": {
                "p.Row": {"k": "key", "label": "label"},
                "q.Row": {"k": "key", "label": "label"},
            },
        }
    }
    pieces = [_piece(tmp_path, "p", "Winner"), _piece(tmp_path, "q", "Loser")]
    built = build(
        pattern(tmp_path, pieces, types),
        "default",
        tmp_path / "out.mosaic",
        pieces=[tmp_path / "p.tessera", tmp_path / "q.tessera"],
        model=StubModel(),
    )
    assert _vectors(built) == {"Item:a": stub_bits("Item a: Winner.  ")}


# --- the text tier does not change vectors made from the same text ------------------------------


def test_text_full_and_text_snippets_give_the_same_vector_hash(tmp_path: Path) -> None:
    # Section 5.4: `full` adds source_text only; the node text (section 6) is the same.
    ev = [evidence("Row:a", "row=1", snippet="passage")]
    mosaics = {"s": {"text": "snippets"}, "f": {"text": "full"}}
    s = _one(
        tmp_path / "s",
        [node("Row:a", "a")],
        ROW,
        mosaics=mosaics,
        target="s",
        evidence=ev,
        text="the whole text of the source",
    )
    f = _one(
        tmp_path / "f",
        [node("Row:a", "a")],
        ROW,
        mosaics=mosaics,
        target="f",
        evidence=ev,
        text="the whole text of the source",
    )
    assert s.knowledge_hash != f.knowledge_hash
    assert s.vector_hash == f.vector_hash


def test_the_vector_hash_changes_when_only_the_label_changes(tmp_path: Path) -> None:
    a = _one(tmp_path / "a", [node("Row:a", "a", label="one")], LABELLED_ROW_LABEL)
    b = _one(tmp_path / "b", [node("Row:a", "a", label="two")], LABELLED_ROW_LABEL)
    assert a.vector_hash != b.vector_hash
    assert a.knowledge_hash != b.knowledge_hash


# --- header settings and the two profiles of one pattern ----------------------------------------


def test_the_header_settings_record_vectors_true_by_default_and_false_when_off(
    tmp_path: Path,
) -> None:
    # Section 3.3: `settings` is the target's entry with every default filled in.
    mosaics = {"default": {}, "off": {"vectors": False}}
    on = _one(tmp_path / "on", [node("Row:a", "a")], ROW, mosaics=mosaics)
    off = _one(tmp_path / "off", [node("Row:a", "a")], ROW, mosaics=mosaics, target="off")
    ((on_settings,),) = _rows(on, "SELECT settings FROM header")
    ((off_settings,),) = _rows(off, "SELECT settings FROM header")
    assert json.loads(on_settings)["vectors"] is True
    assert json.loads(off_settings)["vectors"] is False


def test_vectors_off_leaves_an_empty_vector_table_and_a_passing_check(tmp_path: Path) -> None:
    built = _one(tmp_path, [node("Row:a", "a")], ROW, mosaics={"p": {"vectors": False}}, target="p")
    assert _rows(built, "SELECT count(*) FROM vector") == [(0,)]
    assert _rows(built, "SELECT embed_model, vector_hash FROM header") == [(None, None)]
    report = check_file(built.path, pieces=[tmp_path / "list.tessera"])
    assert report.ok, report.violations


def test_vectors_on_and_off_agree_on_every_knowledge_table(tmp_path: Path) -> None:
    ev = [evidence("Row:a", "row=1", snippet="x")]
    mosaics = {"on": {}, "off": {"vectors": False}}
    on = _one(
        tmp_path / "on",
        [node("Row:a", "a", label="L")],
        LABELLED_ROW_LABEL,
        mosaics=mosaics,
        target="on",
        evidence=ev,
    )
    off = _one(
        tmp_path / "off",
        [node("Row:a", "a", label="L")],
        LABELLED_ROW_LABEL,
        mosaics=mosaics,
        target="off",
        evidence=ev,
    )
    for table in ("node", "edge", "evidence", "snippet", "alias", "source", "type"):
        assert _rows(on, f"SELECT * FROM {table}") == _rows(off, f"SELECT * FROM {table}"), table


# --- failed builds (section 7.3) ----------------------------------------------------------------


def test_a_strict_failure_has_no_hashes_and_writes_no_mosaic(tmp_path: Path) -> None:
    # Section 7.3: a strict target fails after step 7 and the hashes are NULL, vectors on or not.
    refs = [_piece(tmp_path, "p", "One"), _piece(tmp_path, "q", "Two")]
    types = {
        "Item": {
            "key": "k",
            "from": {
                "p.Row": {"k": "key", "label": "label"},
                "q.Row": {"k": "key", "label": "label"},
            },
        }
    }
    with pytest.raises(BuildError) as raised:
        build(
            pattern(tmp_path, refs, types, mosaics={"s": {"strict": True}}),
            "s",
            tmp_path / "out.mosaic",
            pieces=[tmp_path / "p.tessera", tmp_path / "q.tessera"],
            model=StubModel(),
        )
    assert raised.value.reason == "strict"
    report = json.loads((tmp_path / REPORT).read_text(encoding="utf-8"))
    assert (report["knowledge_hash"], report["vector_hash"], report["file_size"]) == (None,) * 3
    assert not (tmp_path / "out.mosaic").exists()


def test_a_budget_that_fits_gives_the_same_vectors_as_no_budget(tmp_path: Path) -> None:
    nodes = [node("Row:a", "a"), node("Row:b", "b")]
    plain = _one(tmp_path / "plain", nodes, ROW)
    fits = _one(tmp_path / "fits", nodes, ROW, mosaics={"b": {"budget": "1 MB"}}, target="b")
    assert plain.vector_hash == fits.vector_hash
    assert _vectors(plain) == _vectors(fits)


# --- the checker on a built mosaic --------------------------------------------------------------


def _tampered(built: Built, tmp_path: Path, statements: list[str]) -> Path:
    copy = tmp_path / "copy.mosaic"
    shutil.copyfile(built.path, copy)
    con = sqlite3.connect(copy)
    try:
        for s in statements:
            con.execute(s)
        con.commit()
    finally:
        con.close()
    return copy


def test_the_checker_refuses_a_built_mosaic_with_one_vector_bit_changed(tmp_path: Path) -> None:
    # Section 3.7: the vector hash binds every bit.
    built = _one(tmp_path / "b", [node("Row:a", "a"), node("Row:b", "b")], ROW)
    copy = _tampered(
        built,
        tmp_path,
        [
            "UPDATE vector SET bits = zeroblob(48) "
            "WHERE nid = (SELECT nid FROM node WHERE id = 'Row:a')"
        ],
    )
    report = check_file(copy, pieces=[tmp_path / "b" / "list.tessera"])
    assert not report.ok
    assert "inv-14" in report.rules


def test_the_checker_refuses_vectors_swapped_between_two_nodes(tmp_path: Path) -> None:
    # Section 3.7: "this binds each vector to its node" -- swapping two vectors changes the hash.
    built = _one(tmp_path / "b", [node("Row:a", "a"), node("Row:b", "b")], ROW)
    copy = _tampered(
        built,
        tmp_path,
        [
            "CREATE TEMP TABLE s AS SELECT nid, bits FROM vector",
            "UPDATE vector SET bits = (SELECT bits FROM s WHERE s.nid != vector.nid)",
        ],
    )
    report = check_file(copy, pieces=[tmp_path / "b" / "list.tessera"])
    assert not report.ok
    assert "inv-14" in report.rules


def test_the_checker_refuses_a_header_that_lost_its_vector_hash(tmp_path: Path) -> None:
    # Section 3.9: when vectors are present, a matching vector hash.
    built = _one(tmp_path / "b", [node("Row:a", "a")], ROW)
    copy = _tampered(built, tmp_path, ["UPDATE header SET vector_hash = NULL, embed_model = NULL"])
    report = check_file(copy, pieces=[tmp_path / "b" / "list.tessera"])
    assert not report.ok
