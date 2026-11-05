"""Steps 2 and 3 of a build: map and merge (Specification 0.1, sections 5.2, 7.1, 3.2, 3.10).

Each test names the rule of the spec or the decision on #14 it checks (Q1-Q9 in the
maintainer's decision comment, written into the spec by #78).
"""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import mosaic_format
import pytest
from mosaic_build.mosaic import Assembly, BuildError, check, merge
from mosaic_build.mosaic.merge import Given
from mosaic_format import knowledge_hash, seal
from mosaic_format.hashes import quote_confidence
from mosaic_format.writer import (
    Alias,
    Content,
    Evidence,
    ExternalRef,
    Header,
    Node,
    Source,
    Type,
)

from tests.mosaic.pieces import PRODUCER, evidence, node, pattern, tessera

type Piece = tuple[str, Sequence[Node], dict[str, Any]]


def assemble(tmp_path: Path, pieces: Sequence[Piece], types: dict[str, Any]) -> Assembly:
    """Seal each ``(name, nodes, tessera keywords)`` piece, write the pattern, run steps 1-3."""
    paths, entries = [], []
    for name, nodes, kwargs in pieces:
        path = tmp_path / f"{name}.tessera"
        entries.append(f"{name}@{tessera(path, nodes, **kwargs)}")
        paths.append(path)
    with check(pattern(tmp_path, entries, types), pieces=paths) as inputs:
        return merge(inputs)


def gauge(fields: dict[str, str], piece: str = "list", **definition: Any) -> dict[str, Any]:
    return {"Gauge": {"key": "tag", **definition, "from": {f"{piece}.Row": fields}}}


def only(a: Assembly) -> Node:
    (n,) = a.node_rows()
    return n


# --- the key (section 5.2; decisions 2, 3 and 4) -------------------------------------------


def test_the_key_property_entry_gives_the_key_which_is_never_a_property(tmp_path: Path) -> None:
    rows = [node("Row:1", "r1", Tag=" g-1 ", Unit="V")]
    a = assemble(
        tmp_path,
        [("list", rows, {})],
        gauge({"tag": "Tag", "unit": "Unit"}, normalise=["trim", "upper"]),
    )
    assert only(a) == Node(id="Gauge:G-1", type="Gauge", key="G-1", props='{"unit": "V"}')


def test_without_a_key_entry_the_key_is_the_piece_node_key(tmp_path: Path) -> None:
    rows = [node("Row:1", " r1", Unit="V")]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"unit": "Unit"}))
    assert (only(a).id, only(a).key) == ("Gauge:r1", "r1")


def test_the_key_field_may_be_a_column(tmp_path: Path) -> None:
    rows = [node("Row:1", "r1", label="Named")]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"tag": "label"}))
    assert (only(a).id, only(a).label) == ("Gauge:Named", "Named")


@pytest.mark.parametrize(
    ("value", "key"),
    [(2020, "2020"), (-7, "-7"), (2.5, "2.5"), (1e21, "1e+21"), (1.0, "1"), (0.000001, "0.000001")],
)
def test_a_number_key_becomes_its_canonical_json_text(
    tmp_path: Path, value: float, key: str
) -> None:
    rows = [node("Row:1", "r1", Year=value)]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"tag": "Year"}))
    assert only(a).key == key
    assert a.aliases() == []  # the number written as text is the key: no alias


@pytest.mark.parametrize(
    ("props", "fields", "what"),
    [
        ({"Other": "x"}, {"tag": "Tag"}, "has no value"),
        ({"Tag": None}, {"tag": "Tag"}, "has no value"),
        ({"Tag": True}, {"tag": "Tag"}, "is a boolean"),
        ({"Tag": [1]}, {"tag": "Tag"}, "is a JSON array"),
        ({"Tag": {"a": 1}}, {"tag": "Tag"}, "is a JSON object"),
        ({"Tag": " \u3000\x85 "}, {"tag": "Tag"}, "is empty after strip and normalisation"),
        ({"Tag": "P_"}, {"tag": "Tag", "strip": "P_"}, "is empty after strip and normalisation"),
        ({}, {"tag": "summary"}, "has no value"),
    ],
)
def test_an_unusable_key_fails_the_build_naming_the_piece_and_node(
    tmp_path: Path, props: dict[str, Any], fields: dict[str, str], what: str
) -> None:
    rows = [node("Row:1", "r1", summary="s", Tag="ok"), node("Row:2", "r2", **props)]
    with pytest.raises(BuildError) as e:
        assemble(tmp_path, [("list", rows, {})], gauge(fields))
    assert e.value.reason == "invalid_input"
    assert "piece 'list', node 'Row:2'" in str(e.value)
    assert what in str(e.value)


def _with_raw_props(path: Path, node_id: str, props: str) -> str:
    """Rewrite one node's props as raw text, as a crafted file could, and reseal its hash."""
    return _crafted(path, "UPDATE node SET props = ? WHERE id = ?", (props, node_id))


def _crafted(path: Path, sql: str, params: tuple[object, ...]) -> str:
    """Change a sealed file with ``sql``, as a crafted file could, and reseal its hash."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute(sql, params)
        con.execute("UPDATE header SET knowledge_hash = ?", (knowledge_hash(con),))
        (h,) = con.execute("SELECT knowledge_hash FROM header").fetchone()
    finally:
        con.close()
    return str(h)


@pytest.mark.parametrize(
    "props",
    ['{"Tag":9007199254740993}', '{"Tag":"a","Tag":"b"}', '{"Unit":"V","Tag":1e400}'],
)
def test_props_that_are_not_i_json_fail_the_build_naming_the_piece_and_node(
    tmp_path: Path, props: str
) -> None:
    path = tmp_path / "list.tessera"
    tessera(path, [node("Row:1", "r1", Tag="g1")])
    h = _with_raw_props(path, "Row:1", props)
    types = gauge({"tag": "Tag"})
    with (
        pytest.raises(BuildError) as e,
        check(pattern(tmp_path, [f"list@{h}"], types), pieces=[path]) as i,
    ):
        merge(i)
    assert e.value.reason == "invalid_input"
    assert "piece 'list', node 'Row:1'" in str(e.value)
    assert "not I-JSON" in str(e.value)


def test_strip_removes_its_prefix_before_normalisation(tmp_path: Path) -> None:
    rows = [
        node("Row:1", "r1", Name="P_volt_2"),
        node("Row:2", "r2", Name="amp_1"),  # no prefix: left as it is
        node("Row:3", "r3", Name=" P_ohm_4"),  # the prefix is not at the start before trim
    ]
    a = assemble(
        tmp_path,
        [("list", rows, {})],
        gauge(
            {"tag": "Name", "strip": "P_"},
            normalise=["trim", "upper", "underscore-to-dash"],
        ),
    )
    assert [n.id for n in a.node_rows()] == ["Gauge:VOLT-2", "Gauge:AMP-1", "Gauge:P-OHM-4"]


def test_the_key_as_written_before_strip_is_an_alias_of_origin_source(tmp_path: Path) -> None:
    rows = [
        node("Row:1", "r1", Name="P_volt_2"),
        node("Row:2", "r2", Name="AMP-1"),  # written as the key is: no alias
    ]
    a = assemble(
        tmp_path,
        [("list", rows, {})],
        gauge({"tag": "Name", "strip": "P_"}, normalise=["upper", "underscore-to-dash"]),
    )
    assert a.aliases() == [Alias(text="P_volt_2", node="Gauge:VOLT-2", origin="source")]


@pytest.mark.parametrize(
    ("steps", "key"),
    [
        (["trim"], "a  b-c_d"),
        (["trim", "upper"], "A  B-C_D"),
        (["trim", "lower", "collapse-spaces"], "a b-c_d"),
        (["collapse-spaces"], " a b-c_d "),
        (["trim", "dash-to-underscore"], "a  b_c_d"),
        (["trim", "underscore-to-dash"], "a  b-c-d"),
    ],
)
def test_each_normalisation_step_applies_to_the_key(
    tmp_path: Path, steps: list[str], key: str
) -> None:
    rows = [node("Row:1", "r1", Name="\ta  b-C_d\u3000".replace("C", "c"))]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"tag": "Name"}, normalise=steps))
    assert only(a).key == key


def test_without_normalise_the_key_is_trimmed(tmp_path: Path) -> None:
    rows = [node("Row:1", "r1", Name="\u2003Abc ")]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"tag": "Name"}))
    assert only(a).key == "Abc"


# --- label, summary and props (section 5.2; decision 1) ------------------------------------


def test_label_and_summary_are_copied_from_the_piece_node_by_default(tmp_path: Path) -> None:
    rows = [node("Row:1", "g1", label="First", summary="The first one", Unit="V")]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"unit": "Unit"}))
    n = only(a)
    assert (n.label, n.summary, n.props) == ("First", "The first one", '{"unit": "V"}')


def test_a_label_or_summary_entry_fills_the_column_not_props(tmp_path: Path) -> None:
    rows = [node("Row:1", "g1", label="Lab", summary="Sum", Name="Named")]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"label": "Name", "summary": "label"}))
    n = only(a)
    assert (n.label, n.summary, n.props) == ("Named", "Lab", None)


def test_a_label_entry_whose_field_is_absent_leaves_the_label_empty(tmp_path: Path) -> None:
    rows = [node("Row:1", "g1", label="Lab")]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"label": "Name"}))
    assert only(a).label is None


def test_a_label_that_is_not_text_fails_the_build(tmp_path: Path) -> None:
    rows = [node("Row:1", "g1", Name=12)]
    with pytest.raises(BuildError) as e:
        assemble(tmp_path, [("list", rows, {})], gauge({"label": "Name"}))
    assert e.value.reason == "invalid_input"
    assert "piece 'list', node 'Row:1'" in str(e.value)


def test_every_other_entry_fills_a_property_of_any_json_value(tmp_path: Path) -> None:
    value = {"low": 0, "high": [1, 2.5], "on": True}
    rows = [node("Row:1", "g1", label="L", Range=value, Unit="V", Note=None)]
    a = assemble(
        tmp_path,
        [("list", rows, {})],
        gauge({"range": "Range", "unit": "Unit", "note": "Note", "name": "label", "id": "key"}),
    )
    assert json.loads(only(a).props or "") == {
        "range": value,
        "unit": "V",
        "name": "L",
        "id": "g1",
    }  # Note is JSON null: no value, so no property


# --- priority order and conflicts (section 7.1 step 3; decision 5) -------------------------


def _two_pieces(first: dict[str, Any], second: dict[str, Any]) -> list[Piece]:
    return [
        ("first", [node("Row:1", "g1", **first)], {"source": "first.csv"}),
        ("second", [node("Row:1", "g1", **second)], {"source": "second.csv"}),
    ]


TWO: dict[str, Any] = {
    "Gauge": {
        "key": "tag",
        "from": {
            "second.Row": {"unit": "Unit"},  # pattern order does not set priority; pieces does
            "first.Row": {"unit": "Unit"},
        },
    }
}


def test_the_earliest_piece_wins_and_a_differing_value_is_a_conflict(tmp_path: Path) -> None:
    a = assemble(tmp_path, _two_pieces({"Unit": "V"}, {"Unit": "mV"}), TWO)
    assert json.loads(only(a).props or "") == {"unit": "V"}
    (c,) = a.conflicts()
    assert (c.node, c.property) == ("Gauge:g1", "unit")
    assert (c.winner.value, c.winner.piece) == ("V", "first")
    assert [(g.value, g.piece) for g in c.losers] == [("mV", "second")]


def test_piece_order_is_priority(tmp_path: Path) -> None:
    pieces = _two_pieces({"Unit": "V"}, {"Unit": "mV"})
    a = assemble(tmp_path, pieces[::-1], TWO)
    assert json.loads(only(a).props or "") == {"unit": "mV"}
    assert [(g.value, g.piece) for g in a.conflicts()[0].losers] == [("V", "first")]


def test_equal_values_are_no_conflict_even_when_spelled_differently(tmp_path: Path) -> None:
    a = assemble(tmp_path, _two_pieces({"Unit": 1}, {"Unit": 1.0}), TWO)
    assert a.conflicts() == []


def test_a_value_only_a_later_piece_gives_fills_the_property(tmp_path: Path) -> None:
    a = assemble(tmp_path, _two_pieces({}, {"Unit": "mV"}), TWO)
    assert json.loads(only(a).props or "") == {"unit": "mV"}
    assert a.conflicts() == []


def test_label_and_summary_conflicts_are_recorded_like_any_property(tmp_path: Path) -> None:
    pieces: list[Piece] = [
        ("first", [node("Row:1", "g1", label="One", summary="S")], {"source": "first.csv"}),
        ("second", [node("Row:1", "g1", label="Uno", summary="S")], {"source": "second.csv"}),
    ]
    a = assemble(tmp_path, pieces, TWO)
    assert only(a).label == "One"
    assert [(c.property, c.winner.value, [g.value for g in c.losers]) for c in a.conflicts()] == [
        ("label", "One", ["Uno"])
    ]


def test_conflicts_list_every_differing_value_once_in_build_order(tmp_path: Path) -> None:
    pieces: list[Piece] = [
        ("a", [node("Row:1", "g1", Unit="V")], {"source": "a.csv"}),
        ("b", [node("Row:1", "g1", Unit="mV"), node("Row:2", "g1 ", Unit="mV")], {}),
        ("c", [node("Row:1", "g1", Unit="kV")], {}),
        ("d", [node("Row:1", "g1", Unit="V")], {}),
    ]
    types = {"Gauge": {"key": "tag", "from": {f"{p}.Row": {"unit": "Unit"} for p in "dcba"}}}
    a = assemble(tmp_path, pieces, types)
    (c,) = a.conflicts()
    assert [(g.value, g.piece) for g in c.losers] == [("mV", "b"), ("kV", "c")]


CODE: dict[str, Any] = {
    "Gauge": {
        "key": "tag",
        "normalise": ["upper", "underscore-to-dash"],
        "from": {
            "code.Define": {"tag": "Name", "unit": "Unit"},
            "code.Macro": {"tag": "Name", "unit": "Unit"},
        },
    }
}
CODE_NODES = [
    node("Macro:1", "m1", Name="G_1", Unit="mV"),
    node("Define:1", "d1", Name="g_1", Unit="V"),
]


def test_within_a_piece_from_entries_in_pattern_order_set_the_build_order(
    tmp_path: Path,
) -> None:
    a = assemble(tmp_path, [("code", CODE_NODES, {})], CODE)
    assert json.loads(only(a).props or "") == {"unit": "V"}
    (c,) = a.conflicts()
    assert (c.winner, c.losers) == (Given("V", "code", 0), (Given("mV", "code", 0),))
    # Aliases are added in the same order: the Define's spelling is kept.
    assert a.aliases() == [Alias(text="g_1", node="Gauge:G-1", origin="source")]
    (ac,) = a.alias_conflicts()
    assert (ac.winner.value, [g.value for g in ac.losers]) == ("g_1", ["G_1"])
    assert (ac.winner.piece, ac.losers[0].piece) == ("code", "code")


def test_reversing_the_from_entries_reverses_the_winner(tmp_path: Path) -> None:
    macro_first = {
        "Gauge": {**CODE["Gauge"], "from": dict(reversed(CODE["Gauge"]["from"].items()))}
    }
    a = assemble(tmp_path, [("code", CODE_NODES, {})], macro_first)
    assert json.loads(only(a).props or "") == {"unit": "mV"}
    assert a.aliases() == [Alias(text="G_1", node="Gauge:G-1", origin="source")]


def test_within_an_entry_piece_nodes_are_taken_in_nid_order(tmp_path: Path) -> None:
    rows = [
        node("Row:2", "r2", Name="g_1", Unit="mV"),
        node("Row:1", "r1", Name="G_1", Unit="V"),  # Row:1 has the lower nid
    ]
    types = gauge({"tag": "Name", "unit": "Unit"}, normalise=["upper", "underscore-to-dash"])
    a = assemble(tmp_path, [("list", rows, {})], types)
    assert json.loads(only(a).props or "") == {"unit": "V"}
    assert [g.value for g in a.conflicts()[0].losers] == ["mV"]
    assert a.aliases() == [Alias(text="G_1", node="Gauge:G-1", origin="source")]


def test_canonical_maps_each_piece_node_to_its_canonical_node(tmp_path: Path) -> None:
    rows = [node("Row:1", "a"), node("Row:2", "b"), node("Row:3", "a ")]
    a = assemble(tmp_path, [("list", rows, {})], gauge({"tag": "key"}))
    assert a.canonical == {
        ("list", "Row:1"): ("Gauge:a",),
        ("list", "Row:2"): ("Gauge:b",),
        ("list", "Row:3"): ("Gauge:a",),
    }


def test_a_piece_type_mapped_to_two_types_gives_two_nodes(tmp_path: Path) -> None:
    rows = [node("Row:1", "a", label="A")]
    types = {
        "Gauge": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
        "Meter": {"key": "code", "from": {"list.Row": {"code": "key"}}},
    }
    a = assemble(tmp_path, [("list", rows, {})], types)
    assert [n.id for n in a.node_rows()] == ["Gauge:a", "Meter:a"]
    assert a.canonical == {("list", "Row:1"): ("Gauge:a", "Meter:a")}


# --- aliases (section 7.1 step 3) ----------------------------------------------------------


def test_a_piece_s_own_aliases_come_before_the_aliases_step_2_makes(tmp_path: Path) -> None:
    rows = [node("Row:1", "r1", Name="g_1")]
    own = [Alias(text="G_1", node="Row:1", origin="source")]
    types = gauge({"tag": "Name"}, normalise=["upper", "underscore-to-dash"])
    a = assemble(tmp_path, [("list", rows, {"aliases": own})], types)
    assert a.aliases() == [Alias(text="G_1", node="Gauge:G-1", origin="source")]
    (c,) = a.alias_conflicts()
    assert (c.node, c.winner.value, [g.value for g in c.losers]) == ("Gauge:G-1", "G_1", ["g_1"])


def test_aliases_are_a_union_in_piece_order_equal_under_nocase_kept_once(
    tmp_path: Path,
) -> None:
    pieces: list[Piece] = [
        (
            "first",
            [node("Row:1", "g1")],
            {"source": "f.csv", "aliases": [Alias("Zed", "Row:1", "source")]},
        ),
        (
            "second",
            [node("Row:1", "g1")],
            {
                "source": "s.csv",
                "aliases": [
                    Alias("ZED", "Row:1", "source"),
                    Alias("Écu", "Row:1", "source"),
                    Alias("écu", "Row:1", "source"),  # NOCASE folds ASCII letters only
                ],
            },
        ),
    ]
    a = assemble(tmp_path, pieces, TWO)
    assert sorted(x.text for x in a.aliases()) == ["Zed", "Écu", "écu"]
    (c,) = a.alias_conflicts()
    assert (c.winner, c.losers) == (
        Given("Zed", "first", 0, "source"),
        (Given("ZED", "second", 1, "source"),),
    )


# --- evidence (section 7.1 step 3; decision 6) and sources (section 3.2) -------------------


def test_evidence_prop_is_renamed_to_the_canonical_properties_or_dropped(tmp_path: Path) -> None:
    rows = [node("Row:1", "r1", label="L", Tag="g1", Name="N", Unit="V", Colour="red")]
    ev = [
        evidence("Row:1", "row=1"),
        evidence("Row:1", "row=1;field=Tag", prop="Tag", snippet="g1"),
        evidence("Row:1", "row=1;field=Name", prop="Name"),
        evidence("Row:1", "row=1;field=Unit", prop="Unit"),
        evidence("Row:1", "row=1;field=Colour", prop="Colour"),
        evidence("Row:1", "row=1;field=label", prop="label"),
        evidence("Row:1", "row=1;field=key", prop="key"),
    ]
    types = gauge({"tag": "Tag", "summary": "Name", "title": "Name", "unit": "Unit"})
    a = assemble(tmp_path, [("list", rows, {"evidence": ev})], types)
    got = sorted((e.locator, e.prop or "") for e in a.evidence)
    assert got == [
        ("row=1", ""),  # about the whole node: kept
        ("row=1;field=Name", "summary"),  # one row per property the field fills
        ("row=1;field=Name", "title"),
        ("row=1;field=Tag", "tag"),  # the key property
        ("row=1;field=Unit", "unit"),
        ("row=1;field=label", "label"),  # label is copied by default, so it is mapped
    ]  # Colour and key are not mapped: dropped
    tag = next(e for e in a.evidence if e.prop == "tag")
    assert tag == Evidence(
        subject="Gauge:g1",
        source="list/src.csv",
        locator="row=1;field=Tag",
        method="extracted",
        producer=PRODUCER,
        prop="tag",
        snippet="g1",
    )


def test_without_a_key_entry_evidence_on_the_key_field_is_the_key_property(
    tmp_path: Path,
) -> None:
    rows = [node("Row:1", "g1")]
    ev = [evidence("Row:1", "row=1;field=key", prop="key")]
    a = assemble(tmp_path, [("list", rows, {"evidence": ev})], gauge({"unit": "Unit"}))
    assert [e.prop for e in a.evidence] == ["tag"]


def test_inferred_evidence_keeps_its_confidence(tmp_path: Path) -> None:
    rows = [node("Row:1", "g1")]
    ev = [evidence("Row:1", "row=1", method="inferred", confidence=0.75)]
    a = assemble(tmp_path, [("list", rows, {"evidence": ev})], gauge({"tag": "key"}))
    assert [(e.method, e.confidence, e.via) for e in a.evidence] == [("inferred", 0.75, None)]


def test_evidence_equal_once_confidence_is_compared_as_hashed_is_kept_once(
    tmp_path: Path,
) -> None:
    # Section 3.5: rows are equal with confidence compared as it is hashed (section 3.6),
    # CAST(round(confidence*1000000) AS INTEGER); these two both hash as 700000.
    rows = [node("Row:1", "g1"), node("Row:2", "g1 ")]
    ev = [
        evidence("Row:1", "row=1", method="inferred", confidence=0.7000001),
        evidence("Row:2", "row=1", method="inferred", confidence=0.7000002),
    ]
    a = assemble(tmp_path, [("list", rows, {"evidence": ev})], gauge({"tag": "key"}))
    assert len(a.evidence) == 1
    assert quote_confidence(a.evidence[0].confidence) == b"700000"


def test_exact_duplicate_evidence_is_kept_once(tmp_path: Path) -> None:
    rows = [node("Row:1", "g1"), node("Row:2", "g1 ")]
    ev = [evidence("Row:1", "row=1"), evidence("Row:2", "row=1")]
    a = assemble(tmp_path, [("list", rows, {"evidence": ev})], gauge({"tag": "key"}))
    assert [(e.subject, e.locator) for e in a.evidence] == [("Gauge:g1", "row=1")]


def test_sources_are_the_pieces_then_their_original_sources_prefixed(tmp_path: Path) -> None:
    pieces = _two_pieces({}, {})
    pieces[0][2].update(notice="CC BY 4.0, Example Org", text="tag,unit\n")
    a = assemble(tmp_path, pieces, TWO)
    first = mosaic_format.open(tmp_path / "first.tessera")
    second = mosaic_format.open(tmp_path / "second.tessera")
    with first, second:
        assert a.sources == [
            Source(id="first", kind="tessera", hash=first.knowledge_hash),
            Source(id="second", kind="tessera", hash=second.knowledge_hash),
            Source(
                id="first/first.csv",
                kind="file",
                hash="a" * 64,
                path="first.csv",
                notice="CC BY 4.0, Example Org",
                text="tag,unit\n",
            ),
            Source(id="second/second.csv", kind="file", hash="a" * 64, path="second.csv"),
        ]
    assert {e.source for e in a.evidence} == {"first/first.csv", "second/second.csv"}


# --- external references (section 3.10; decision 9) ----------------------------------------


def test_external_refs_are_a_union_and_equal_ones_keep_the_first_sid(tmp_path: Path) -> None:
    def ref(source: str, series: str) -> ExternalRef:
        return ExternalRef("Row:1", "hist", "timeseries", json.dumps({"series": series}), source)

    pieces = _two_pieces({}, {})
    pieces[0][2]["external_refs"] = [ref("first.csv", "G1")]
    pieces[1][2]["external_refs"] = [ref("second.csv", "G1"), ref("second.csv", "G2")]
    a = assemble(tmp_path, pieces, TWO)
    assert a.external_refs == [
        ExternalRef("Gauge:g1", "hist", "timeseries", '{"series":"G1"}', "first/first.csv"),
        ExternalRef("Gauge:g1", "hist", "timeseries", '{"series":"G2"}', "second/second.csv"),
    ]


def test_a_locator_that_is_not_i_json_fails_the_build_naming_the_piece_and_node(
    tmp_path: Path,
) -> None:
    path = tmp_path / "list.tessera"
    ref = ExternalRef("Row:1", "hist", "timeseries", '{"series":"G1"}', "src.csv")
    tessera(path, [node("Row:1", "g1")], external_refs=[ref])
    h = _crafted(path, "UPDATE external_ref SET locator = ?", ('{"series":1e400}',))
    types = gauge({"tag": "key"})
    with (
        pytest.raises(BuildError) as e,
        check(pattern(tmp_path, [f"list@{h}"], types), pieces=[path]) as i,
    ):
        merge(i)
    assert e.value.reason == "invalid_input"
    assert "piece 'list', node 'Row:1'" in str(e.value)
    assert "locator is not I-JSON" in str(e.value)


# --- a mosaic piece (section 7.1 step 2; decision 7) ---------------------------------------


def _inner_mosaic(path: Path, list_hash: str) -> str:
    content = Content(
        header=Header(kind="mosaic", producer=PRODUCER, pattern_hash="b" * 64, target="t"),
        sources=[
            Source(id="list", kind="tessera", hash=list_hash),
            Source(id="list/src.csv", kind="file", hash="a" * 64, notice="Notice A"),
        ],
        types=[Type(name="Gauge", kind="node", key_prop="tag", props='{"unit":"text"}')],
        nodes=[Node("Gauge:G-1", "Gauge", "G-1", label="One", props='{"unit":"V"}')],
        aliases=[Alias("gee one", "Gauge:G-1", "proposal")],
        evidence=[
            Evidence("Gauge:G-1", "list/src.csv", "row=1", "extracted", PRODUCER),
            Evidence("Gauge:G-1", "list/src.csv", "row=1", "extracted", PRODUCER, prop="unit"),
        ],
    )
    return seal(path, content).knowledge_hash


def test_a_mosaic_piece_s_nodes_are_mapped_by_the_field_map(tmp_path: Path) -> None:
    inner = tmp_path / "base.mosaic"
    h = _inner_mosaic(inner, "c" * 64)
    types = {
        "Meter": {
            "key": "code",
            "normalise": ["lower"],
            "from": {"base.Gauge": {"volts": "unit"}},
        }
    }
    with check(pattern(tmp_path, [f"base@{h}"], types), pieces=[inner]) as inputs:
        a = merge(inputs)
    assert a.node_rows() == [Node("Meter:g-1", "Meter", "g-1", label="One", props='{"volts": "V"}')]
    # Its own aliases first, then the key as written, then its old id with origin pattern.
    assert a.aliases() == [
        Alias("gee one", "Meter:g-1", "proposal"),
        Alias("G-1", "Meter:g-1", "source"),
        Alias("Gauge:G-1", "Meter:g-1", "pattern"),
    ]
    # Its original sources are copied and prefixed again; its piece row is not copied.
    assert [(s.id, s.kind, s.notice) for s in a.sources] == [
        ("base", "mosaic", None),
        ("base/list/src.csv", "file", "Notice A"),
    ]
    # Its evidence names the copied source and has the piece's hash appended to via.
    assert [(e.source, e.prop, e.via) for e in a.evidence] == [
        ("base/list/src.csv", None, json.dumps([h])),
        ("base/list/src.csv", "volts", json.dumps([h])),
    ]


@pytest.mark.parametrize(
    ("via", "what"),
    [("[1e400]", "via is not I-JSON"), ("[1]", "via is not an array of knowledge hashes")],
)
def test_a_via_that_is_not_hashes_fails_the_build_naming_the_piece_and_node(
    tmp_path: Path, via: str, what: str
) -> None:
    inner = tmp_path / "base.mosaic"
    _inner_mosaic(inner, "c" * 64)
    h = _crafted(inner, "UPDATE evidence SET via = ? WHERE prop IS NULL", (via,))
    types = {"Meter": {"key": "code", "from": {"base.Gauge": {"volts": "unit"}}}}
    with (
        pytest.raises(BuildError) as e,
        check(pattern(tmp_path, [f"base@{h}"], types), pieces=[inner]) as i,
    ):
        merge(i)
    assert e.value.reason == "invalid_input"
    assert "piece 'base', node 'Gauge:G-1'" in str(e.value)
    assert what in str(e.value)


def test_evidence_of_a_tessera_with_a_via_fails_the_build(tmp_path: Path) -> None:
    # Section 3.5: via is NULL when the evidence came straight from a tessera.
    path = tmp_path / "list.tessera"
    h = tessera(path, [node("Row:1", "g1")], evidence=[evidence("Row:1", "row=1", via='["x"]')])
    with (
        pytest.raises(BuildError) as e,
        check(pattern(tmp_path, [f"list@{h}"], gauge({"tag": "key"})), pieces=[path]) as i,
    ):
        merge(i)
    assert e.value.reason == "invalid_input"
    assert "piece 'list', node 'Row:1'" in str(e.value)
    assert "evidence of a tessera has a via" in str(e.value)


def test_an_alias_that_differs_only_in_origin_is_no_conflict(tmp_path: Path) -> None:
    inner = tmp_path / "base.mosaic"
    h = _inner_mosaic(inner, "c" * 64)
    first = tmp_path / "first.tessera"
    hf = tessera(first, [node("Row:1", "G-1")], aliases=[Alias("Gauge:G-1", "Row:1", "source")])
    types = {
        "Gauge": {
            "key": "tag",
            "from": {"first.Row": {"tag": "key"}, "base.Gauge": {"tag": "key"}},
        }
    }
    with check(
        pattern(tmp_path, [f"first@{hf}", f"base@{h}"], types), pieces=[first, inner]
    ) as inputs:
        a = merge(inputs)
    assert ("Gauge:G-1", "source") in [(x.text, x.origin) for x in a.aliases()]
    assert a.alias_conflicts() == []


# --- the whole assembly --------------------------------------------------------------------


def test_the_same_inputs_give_the_same_assembly(tmp_path: Path) -> None:
    pieces = _two_pieces({"Unit": "V"}, {"Unit": "mV", "Range": [1, 2]})
    types = {"Gauge": {**TWO["Gauge"], "from": {**TWO["Gauge"]["from"]}}}
    types["Gauge"]["from"]["second.Row"] = {"unit": "Unit", "range": "Range"}
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    a, b = assemble(one, pieces, types), assemble(two, pieces, types)
    assert a.node_rows() == b.node_rows()
    assert (a.evidence, a.sources, a.conflicts()) == (b.evidence, b.sources, b.conflicts())


def test_the_assembly_seals_into_a_mosaic_the_reading_rules_accept(tmp_path: Path) -> None:
    rows = [node("Row:1", "r1", label="One", Name="P_volt_2", Unit="V")]
    a = assemble(
        tmp_path,
        [("list", rows, {})],
        gauge({"tag": "Name", "unit": "Unit", "strip": "P_"}, normalise=["upper"]),
    )
    content = Content(
        header=Header(kind="mosaic", producer=PRODUCER, pattern_hash="b" * 64, target="t"),
        sources=a.sources,
        types=[Type(name="Gauge", kind="node", key_prop="tag", props='{"unit":"text"}')],
        nodes=a.node_rows(),
        aliases=a.aliases(),
        evidence=a.evidence,
        external_refs=a.external_refs,
    )
    seal(tmp_path / "out.mosaic", content)
    with mosaic_format.open(tmp_path / "out.mosaic") as m:
        assert m.query("SELECT id, label, props FROM node") == [
            ("Gauge:VOLT_2", "One", '{"unit":"V"}')
        ]
        assert m.query("SELECT text, origin FROM alias") == [("P_volt_2", "source")]
