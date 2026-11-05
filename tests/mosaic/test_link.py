"""Steps 4 and 5 of a build: identity proposals and link (Specification 0.1, sections 5.3,
5.5, 7, 7.1 steps 4-5 and 7.2).

Each test names the rule it checks; Q1-Q7 are the maintainer's decisions on #15.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import mosaic_format
import pytest
from mosaic_build.mosaic import (
    Assembly,
    BuildError,
    MentionReport,
    ProposalStatus,
    StaleReference,
    apply_identities,
    check,
    link,
    merge,
)
from mosaic_build.mosaic.merge import Given
from mosaic_format import seal
from mosaic_format.writer import (
    Alias,
    Content,
    Edge,
    EdgeKey,
    Evidence,
    ExternalRef,
    Header,
    Mention,
    Node,
    Source,
    Type,
)

from tests.mosaic.pieces import (
    PRODUCER,
    edge_proposal,
    evidence,
    identity,
    node,
    pattern,
    proposals,
    tessera,
)

type Piece = tuple[str, Sequence[Node], dict[str, Any]]


def build(
    tmp_path: Path,
    pieces: Sequence[Piece],
    types: dict[str, Any],
    edges: dict[str, Any] | None = None,
    entries: Sequence[dict[str, Any]] | None = None,
    *,
    built_from: str = "0" * 64,
    previous: Path | None = None,
) -> Assembly:
    """Seal each piece, write the pattern (and proposals), and run steps 1-5."""
    paths, listed = [], []
    for name, nodes, kwargs in pieces:
        path = tmp_path / f"{name}.tessera"
        listed.append(f"{name}@{tessera(path, nodes, **kwargs)}")
        paths.append(path)
    proposals_path = None if entries is None else proposals(tmp_path, entries, built_from)
    with check(
        pattern(tmp_path, listed, types, edges),
        pieces=paths,
        proposals=proposals_path,
        previous=previous,
    ) as inputs:
        a = merge(inputs)
        apply_identities(inputs, a)
        link(inputs, a)
        return a


SENSOR = {"Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}}}
"""Sensors keyed by the piece node's key, from piece ``list``."""


def sensors(*keys: str, **kwargs: Any) -> Piece:
    """Piece ``list``: one ``Row`` per key, labelled ``L<key>``."""
    return ("list", [node(f"Row:{k}", k, label=f"L{k}") for k in keys], kwargs)


def ids(a: Assembly) -> list[str]:
    return list(a.nodes)


def aliases(a: Assembly, node_id: str) -> list[tuple[str, str]]:
    return [(x.text, x.origin) for x in a.aliases() if x.node == node_id]


def statuses(a: Assembly) -> list[tuple[str, str]]:
    return [(p.id, p.status) for p in a.proposals]


# --- step 4: identity proposals (section 5.5, section 7.1 step 4) ---------------------------


def test_same_as_names_become_proposal_aliases_in_listed_order(tmp_path: Path) -> None:
    piece = sensors("A", aliases=[Alias("first", "Row:A", "source")])
    a = build(tmp_path, [piece], SENSOR, entries=[identity("p1", "Sensor:A", ["zeta", "alpha"])])
    assert aliases(a, "Sensor:A") == [
        ("first", "source"),
        ("zeta", "proposal"),
        ("alpha", "proposal"),
    ]


def test_open_and_rejected_proposals_have_no_effect(tmp_path: Path) -> None:
    entries = [
        identity("p1", "Sensor:A", ["Sensor:B", "other"], decision="open"),
        identity("p2", "Sensor:A", ["Sensor:B", "other"], decision="rejected"),
    ]
    a = build(tmp_path, [sensors("A", "B")], SENSOR, entries=entries)
    assert ids(a) == ["Sensor:A", "Sensor:B"]
    assert aliases(a, "Sensor:A") == []
    assert all(s.id != "proposals.yaml" for s in a.sources)
    assert a.proposals == []


def test_an_id_in_same_as_merges_its_node_into_node(tmp_path: Path) -> None:
    rows = [node("Row:A", "A", label="LA"), node("Row:B", "B", label="LB", unit="V")]
    piece = (
        "list",
        rows,
        {
            "aliases": [Alias("bee", "Row:B", "source"), Alias("b2", "Row:B", "source")],
            "external_refs": [ExternalRef("Row:B", "erp", "item", '{"n":2}', "src.csv")],
        },
    )
    types = {"Sensor": {"key": "tag", "from": {"list.Row": {"unit": "unit"}}}}
    a = build(tmp_path, [piece], types, entries=[identity("p1", "Sensor:A", ["Sensor:B"])])
    assert ids(a) == ["Sensor:A"]
    # The name, then the merged node's own aliases right after, in their alias order, then
    # its key (#86).
    assert aliases(a, "Sensor:A") == [
        ("Sensor:B", "proposal"),
        ("b2", "source"),
        ("bee", "source"),
        ("B", "proposal"),
    ]
    # Its evidence and external references move to node.
    assert {e.locator for e in a.evidence if e.subject == "Sensor:A"} == {
        "file=src.csv;row=1",
        "file=src.csv;row=2",
    }
    assert all(e.subject != "Sensor:B" for e in a.evidence)
    assert [(x.node, x.system) for x in a.external_refs] == [("Sensor:A", "erp")]
    # Its piece nodes map to node from then on.
    assert a.canonical[("list", "Row:B")] == ("Sensor:A",)
    # A property only the merged node had fills node's; same piece, label conflict in order.
    (n,) = a.node_rows()
    assert (n.label, n.props) == ("LA", '{"unit": "V"}')
    assert [(c.node, c.property, c.winner.value) for c in a.conflicts()] == [
        ("Sensor:A", "label", "LA")
    ]


def test_across_merged_nodes_the_earliest_piece_wins_each_property(tmp_path: Path) -> None:
    first = ("first", [node("Row:B", "B", label="from first")], {})
    second = ("second", [node("Row:A", "A", label="from second")], {})
    types = {
        "Sensor": {
            "key": "tag",
            "from": {"first.Row": {"tag": "key"}, "second.Row": {"tag": "key"}},
        }
    }
    a = build(tmp_path, [first, second], types, entries=[identity("p1", "Sensor:A", ["Sensor:B"])])
    (n,) = a.node_rows()
    assert (n.id, n.label) == ("Sensor:A", "from first")
    (c,) = a.conflicts()
    assert (c.winner, c.losers) == (
        Given("from first", "first", 0),
        (Given("from second", "second", 1),),
    )


def test_a_proposal_alias_that_loses_under_nocase_names_proposals_yaml(tmp_path: Path) -> None:
    piece = sensors("A", aliases=[Alias("Gauge", "Row:A", "source")])
    a = build(tmp_path, [piece], SENSOR, entries=[identity("p1", "Sensor:A", ["GAUGE"])])
    (c,) = a.alias_conflicts()
    assert (c.node, c.winner.value, c.winner.piece) == ("Sensor:A", "Gauge", "list")
    assert [(g.value, g.piece) for g in c.losers] == [("GAUGE", "proposals.yaml")]


def test_an_id_merged_away_stands_for_the_node_it_was_merged_into(tmp_path: Path) -> None:
    entries = [
        identity("p1", "Sensor:B", ["Sensor:C"]),
        identity("p2", "Sensor:A", ["Sensor:B"]),
        # Sensor:C → Sensor:B → Sensor:A: following each merge in turn, D joins A.
        identity("p3", "Sensor:C", ["Sensor:D"]),
    ]
    a = build(tmp_path, [sensors("A", "B", "C", "D")], SENSOR, entries=entries)
    assert ids(a) == ["Sensor:A"]
    assert a.canonical[("list", "Row:D")] == ("Sensor:A",)
    assert statuses(a) == []


def test_a_proposal_that_would_merge_a_node_into_itself_merges_nothing(tmp_path: Path) -> None:
    entries = [identity("p1", "Sensor:A", ["Sensor:B"]), identity("p2", "Sensor:B", ["Sensor:A"])]
    a = build(tmp_path, [sensors("A", "B")], SENSOR, entries=entries)
    assert ids(a) == ["Sensor:A"]
    assert statuses(a) == []
    assert ("Sensor:A", "proposal") in aliases(a, "Sensor:A")


def test_an_identity_proposal_whose_node_is_not_in_the_build_no_longer_applies(
    tmp_path: Path,
) -> None:
    entries = [identity("p1", "Sensor:Z", ["Sensor:A", "zed"])]
    a = build(tmp_path, [sensors("A")], SENSOR, entries=entries)
    assert ids(a) == ["Sensor:A"]
    assert aliases(a, "Sensor:A") == []
    assert a.proposals == [ProposalStatus("p1", "no_longer_applies")]
    assert all(s.id != "proposals.yaml" for s in a.sources)


def test_a_same_as_id_naming_no_node_only_becomes_an_alias(tmp_path: Path) -> None:
    a = build(tmp_path, [sensors("A")], SENSOR, entries=[identity("p1", "Sensor:A", ["Sensor:Q"])])
    assert aliases(a, "Sensor:A") == [("Sensor:Q", "proposal")]
    assert a.proposals == []


def test_applied_proposals_add_proposals_yaml_as_a_file_source(tmp_path: Path) -> None:
    a = build(tmp_path, [sensors("A")], SENSOR, entries=[identity("p1", "Sensor:A", ["x"])])
    data = (tmp_path / "proposals.yaml").read_bytes()
    assert a.sources[-1] == Source(
        id="proposals.yaml",
        kind="file",
        hash=hashlib.sha256(data).hexdigest(),
        path="proposals.yaml",
    )


# --- outdated proposals (section 5.5, section 7; Q2) ----------------------------------------


def _previous(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "previous.mosaic"
    content = Content(
        header=Header(kind="mosaic", producer=PRODUCER, pattern_hash="b" * 64, target="t"),
        sources=[
            Source(id="list", kind="tessera", hash="c" * 64),
            Source(id="list/src.csv", kind="file", hash="a" * 64),
        ],
        types=[Type(name="Sensor", kind="node", key_prop="tag")],
        nodes=[Node("Sensor:A", "Sensor", "A"), Node("Sensor:B", "Sensor", "B")],
        evidence=[
            Evidence("Sensor:A", "list/src.csv", "row=1", "extracted", PRODUCER),
            Evidence("Sensor:B", "list/src.csv", "row=2", "extracted", PRODUCER),
        ],
    )
    return path, seal(path, content).knowledge_hash


def test_without_the_previous_mosaic_no_proposal_is_outdated(tmp_path: Path) -> None:
    entries = [identity("p1", "Sensor:A", ["x"])]
    a = build(tmp_path, [sensors("A")], SENSOR, entries=entries, built_from="f" * 64)
    assert a.proposals == []


def test_every_proposal_is_outdated_when_built_from_is_not_the_previous_mosaic(
    tmp_path: Path,
) -> None:
    previous, _ = _previous(tmp_path)
    entries = [
        identity("p1", "Sensor:A", ["x"]),
        identity("p2", "Sensor:A", ["y"], decision="open"),
        identity("p3", "Sensor:A", ["z"], decision="rejected"),
    ]
    a = build(
        tmp_path, [sensors("A")], SENSOR, entries=entries, built_from="f" * 8, previous=previous
    )
    assert statuses(a) == [("p1", "outdated"), ("p2", "outdated"), ("p3", "outdated")]
    # An accepted outdated proposal is still applied: only the report is affected.
    assert aliases(a, "Sensor:A") == [("x", "proposal")]


def test_built_from_a_prefix_of_the_previous_mosaic_is_not_outdated(tmp_path: Path) -> None:
    previous, h = _previous(tmp_path)
    entries = [identity("p1", "Sensor:A", ["x"])]
    a = build(
        tmp_path, [sensors("A")], SENSOR, entries=entries, built_from=h[:8], previous=previous
    )
    assert a.proposals == []


def test_an_outdated_proposal_that_no_longer_applies_is_listed_twice(tmp_path: Path) -> None:
    previous, _ = _previous(tmp_path)
    entries = [identity("p1", "Sensor:Z", ["x"])]
    a = build(
        tmp_path, [sensors("A")], SENSOR, entries=entries, built_from="f" * 8, previous=previous
    )
    assert statuses(a) == [("p1", "outdated"), ("p1", "no_longer_applies")]


def test_the_previous_mosaic_checks_proposal_ids_when_it_is_their_built_from(
    tmp_path: Path,
) -> None:
    # Section 5.6: when the built_from mosaic is available, proposal ids MUST exist in it.
    previous, h = _previous(tmp_path)
    entries = [identity("p1", "Sensor:Z", ["x"])]
    with pytest.raises(BuildError) as e:
        build(tmp_path, [sensors("A")], SENSOR, entries=entries, built_from=h, previous=previous)
    assert e.value.reason == "invalid_input"
    assert "Sensor:Z" in str(e.value)


def test_a_previous_mosaic_the_reading_rules_refuse_fails_the_build(tmp_path: Path) -> None:
    bad = tmp_path / "previous.mosaic"
    bad.write_bytes(b"not a database")
    with pytest.raises(BuildError) as e:
        build(tmp_path, [sensors("A")], SENSOR, entries=[], previous=bad)
    assert e.value.reason == "invalid_input"
    assert "previous" in str(e.value)


# --- step 5: map edges (section 5.3; Q5) ----------------------------------------------------

TWO_TYPES = {
    "Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
    "Unit": {"key": "code", "normalise": ["upper"], "from": {"list.U": {"code": "key"}}},
}


def measured(edges: Sequence[Edge], **kwargs: Any) -> Piece:
    rows = [node("Row:A", "A"), node("Row:B", "B"), node("U:v", "v"), node("U:a", "a")]
    return ("list", rows, {"edges": edges, **kwargs})


MEASURED_IN = {"measured_in": {"from": "Sensor", "to": "Unit", "map": ["list.in"]}}


def test_map_copies_piece_edges_with_qualifier_props_and_evidence(tmp_path: Path) -> None:
    e = Edge("in", "Row:A", "U:v", qualifier="main", props='{"scale":2}')
    ev = [
        evidence("Row:A", "row=1"),
        evidence("Row:B", "row=2"),
        evidence("U:v", "row=3"),
        evidence("U:a", "row=4"),
        evidence(e.key, "row=1;field=unit", prop="scale", snippet="x2"),
        evidence(e.key, "row=1", method="inferred", confidence=0.5),
    ]
    a = build(tmp_path, [measured([e], evidence=ev)], TWO_TYPES, MEASURED_IN)
    key = EdgeKey("Sensor:A", "measured_in", "Unit:V", "main")
    assert a.edge_rows() == [Edge("measured_in", "Sensor:A", "Unit:V", "main", '{"scale": 2}')]
    assert {x for x in a.evidence if x.subject == key} == {
        Evidence(key, "list/src.csv", "row=1;field=unit", "extracted", PRODUCER, "scale", None,
                 None, "x2"),
        Evidence(key, "list/src.csv", "row=1", "inferred", PRODUCER, None, 0.5),
    }  # fmt: skip


def test_only_the_listed_piece_edge_types_are_copied(tmp_path: Path) -> None:
    edges = [Edge("in", "Row:A", "U:v"), Edge("near", "Row:B", "U:a")]
    a = build(tmp_path, [measured(edges)], TWO_TYPES, MEASURED_IN)
    assert [x.key for x in a.edge_rows()] == [EdgeKey("Sensor:A", "measured_in", "Unit:V")]


def test_an_edge_with_an_end_of_no_declared_type_is_not_copied_or_reported(
    tmp_path: Path,
) -> None:
    # Piece edges "at" end at V nodes, which map to no Unit (nor to anything else).
    name, rows, kwargs = measured([Edge("in", "Row:A", "U:v"), Edge("at", "Row:B", "V:w")])
    piece = (name, [*rows, node("V:w", "w")], kwargs)
    edges = {"measured_in": {"from": "Sensor", "to": "Unit", "map": ["list.in", "list.at"]}}
    a = build(tmp_path, [piece], TWO_TYPES, edges)
    assert [x.key for x in a.edge_rows()] == [EdgeKey("Sensor:A", "measured_in", "Unit:V")]
    assert (a.mentions, a.stale_references, a.edge_conflicts()) == ([], [], [])


def test_an_edge_of_a_merged_node_is_made_at_the_node_it_was_merged_into(tmp_path: Path) -> None:
    edges = [Edge("in", "Row:B", "U:v")]
    entries = [identity("p1", "Sensor:A", ["Sensor:B"])]
    a = build(tmp_path, [measured(edges)], TWO_TYPES, MEASURED_IN, entries)
    assert [x.key for x in a.edge_rows()] == [EdgeKey("Sensor:A", "measured_in", "Unit:V")]


def test_edges_that_become_one_merge_props_key_by_key_earliest_piece_wins(
    tmp_path: Path,
) -> None:
    def piece(name: str, props: str) -> Piece:
        rows = [node("Row:A", "A"), node("U:v", "v")]
        return (name, rows, {"edges": [Edge("in", "Row:A", "U:v", props=props)]})

    types = {
        "Sensor": {"key": "tag", "from": {"one.Row": {"tag": "key"}, "two.Row": {"tag": "key"}}},
        "Unit": {"key": "code", "from": {"one.U": {"code": "key"}, "two.U": {"code": "key"}}},
    }
    edges = {"measured_in": {"from": "Sensor", "to": "Unit", "map": ["one.in", "two.in"]}}
    a = build(
        tmp_path,
        [piece("one", '{"scale":2,"x":1}'), piece("two", '{"scale":3,"y":true,"x":1.0}')],
        types,
        edges,
    )
    (e,) = a.edge_rows()
    assert json.loads(str(e.props)) == {"scale": 2, "x": 1, "y": True}
    # Both pieces' evidence is kept on the one edge.
    assert {x.source for x in a.evidence if x.subject == e.key} == {"one/src.csv", "two/src.csv"}
    (c,) = a.edge_conflicts()
    assert (c.edge, c.property) == (EdgeKey("Sensor:A", "measured_in", "Unit:v"), "scale")
    assert (c.winner, c.losers) == (Given(2, "one", 0), (Given(3, "two", 1),))


def test_edge_conflicts_are_sorted_by_from_type_to_qualifier_and_property(
    tmp_path: Path,
) -> None:
    def piece(name: str, value: int) -> Piece:
        rows = [node("Row:A", "A"), node("Row:B", "B"), node("U:v", "v")]
        edges = [
            Edge("in", "Row:B", "U:v", props=json.dumps({"q": value, "p": value})),
            Edge("in", "Row:A", "U:v", qualifier="z", props=json.dumps({"p": value})),
            Edge("in", "Row:A", "U:v", qualifier="a", props=json.dumps({"p": value})),
        ]
        return (name, rows, {"edges": edges})

    types = {
        "Sensor": {"key": "tag", "from": {"one.Row": {"tag": "key"}, "two.Row": {"tag": "key"}}},
        "Unit": {"key": "code", "from": {"one.U": {"code": "key"}, "two.U": {"code": "key"}}},
    }
    edges = {"measured_in": {"from": "Sensor", "to": "Unit", "map": ["one.in", "two.in"]}}
    a = build(tmp_path, [piece("one", 1), piece("two", 2)], types, edges)
    assert [(c.edge.src, c.edge.qualifier, c.property) for c in a.edge_conflicts()] == [
        ("Sensor:A", "a", "p"),
        ("Sensor:A", "z", "p"),
        ("Sensor:B", "", "p"),
        ("Sensor:B", "", "q"),
    ]


def test_piece_edge_props_that_are_not_i_json_fail_the_build(tmp_path: Path) -> None:
    from tests.mosaic.test_map_merge import _crafted

    path = tmp_path / "list.tessera"
    rows = [node("Row:A", "A"), node("U:v", "v")]
    tessera(path, rows, edges=[Edge("in", "Row:A", "U:v", props='{"s":1}')])
    h = _crafted(path, "UPDATE edge SET props = ?", ('{"s":1,"s":2}',))
    with (
        check(pattern(tmp_path, [f"list@{h}"], TWO_TYPES, MEASURED_IN), pieces=[path]) as inputs,
        pytest.raises(BuildError) as e,
    ):
        a = merge(inputs)
        link(inputs, a)
    assert e.value.reason == "invalid_input"
    assert "piece 'list', edge 'in' from 'Row:A' to 'U:v'" in str(e.value)


# --- step 5: mention rules (section 5.3; Q1, Q6, Q7) ----------------------------------------

DOCS = {
    "Sensor": {"key": "tag", "normalise": ["trim", "upper"], "from": {"list.Row": {"tag": "key"}}},
    "Step": {"key": "n", "from": {"proc.Step": {"n": "key"}}},
}

READS = {"reads": {"from": "Step", "to": "Sensor", "mentions": "verify.*"}}


def procedure(*mentions: tuple[str, str], producer: str = "reader/2.0") -> Piece:
    """Piece ``proc``: one step ``S1`` that mentions each ``(text, role)``."""
    found = [
        Mention(text, f"line={i + 1}", "Step:S1", role, "phrase")
        for i, (text, role) in enumerate(mentions)
    ]
    return (
        "proc",
        [node("Step:S1", "S1")],
        {"source": "proc.txt", "mentions": found, "producer": producer},
    )


def gauges(*keys: str, **kwargs: Any) -> Piece:
    return ("list", [node(f"Row:{k}", k) for k in keys], kwargs)


def reads(a: Assembly) -> list[str]:
    return [e.dst for e in a.edge_rows() if e.type == "reads"]


def test_a_mention_matches_the_key_after_the_to_type_s_normalisation(tmp_path: Path) -> None:
    a = build(tmp_path, [gauges("T-1"), procedure(("  t-1 ", "verify.arg0"))], DOCS, READS)
    assert a.edge_rows() == [Edge("reads", "Step:S1", "Sensor:T-1")]
    assert (a.mentions, a.stale_references) == ([], [])


def test_a_mention_edge_has_one_extracted_row_sourced_to_the_piece_s_source(
    tmp_path: Path,
) -> None:
    a = build(tmp_path, [gauges("T-1"), procedure(("T-1", "verify.arg0"))], DOCS, READS)
    key = EdgeKey("Step:S1", "reads", "Sensor:T-1")
    assert [x for x in a.evidence if x.subject == key] == [
        Evidence(key, "proc/proc.txt", "line=1", "extracted", "reader/2.0")
    ]


def test_the_key_match_ignores_strip_and_compares_bytes(tmp_path: Path) -> None:
    types = {
        "Sensor": {"key": "tag", "normalise": [], "from": {"list.Row": {"strip": "P_"}}},
        "Step": DOCS["Step"],
    }
    # Strip would turn "P_T1" into the key "T1"; "t1" differs from it in bytes.
    piece = procedure(("P_T1", "verify.a"), ("t1", "verify.b"), ("T1", "verify.c"))
    a = build(tmp_path, [gauges("T1"), piece], types, READS)
    assert reads(a) == ["Sensor:T1"]
    assert [m.text for m in a.mentions] == ["P_T1", "t1"]


def test_a_mention_matches_an_alias_under_nocase(tmp_path: Path) -> None:
    piece = gauges("T-1", aliases=[Alias("Temp One", "Row:T-1", "source")])
    a = build(tmp_path, [piece, procedure(("TEMP ONE", "verify.x"))], DOCS, READS)
    assert reads(a) == ["Sensor:T-1"]


def test_nocase_folds_only_ascii_letters(tmp_path: Path) -> None:
    piece = gauges("T-1", aliases=[Alias("Ärger", "Row:T-1", "source")])
    a = build(
        tmp_path, [piece, procedure(("äRGER", "verify.x"), ("ÄRGER", "verify.y"))], DOCS, READS
    )
    assert reads(a) == ["Sensor:T-1"]
    assert [(m.text, m.status) for m in a.mentions] == [("äRGER", "unmatched")]


def test_aliases_from_accepted_identity_proposals_take_part(tmp_path: Path) -> None:
    entries = [identity("p1", "Sensor:T-1", ["thermo"])]
    a = build(tmp_path, [gauges("T-1"), procedure(("Thermo", "verify.x"))], DOCS, READS, entries)
    assert reads(a) == ["Sensor:T-1"]


# A merged node's key stays an alias (section 7.1 step 4, #86).

MERGE_TMP3 = [identity("p1", "Sensor:TEMP-3", ["Sensor:TMP3"])]
GAUGES = {"Sensor": DOCS["Sensor"]}


def test_a_merged_node_s_key_becomes_a_proposal_alias_so_its_mentions_still_match(
    tmp_path: Path,
) -> None:
    # The key is written as normalised, so step 2 makes no alias from it.
    pieces = [gauges("TEMP-3", "TMP3"), procedure(("TMP3", "verify.arg0"))]
    a = build(tmp_path, pieces, DOCS, READS, MERGE_TMP3)
    assert ids(a) == ["Sensor:TEMP-3", "Step:S1"]
    assert reads(a) == ["Sensor:TEMP-3"]
    assert (a.mentions, a.stale_references) == ([], [])
    assert ("TMP3", "proposal") in aliases(a, "Sensor:TEMP-3")


def test_a_merged_key_equal_under_nocase_to_an_alias_node_has_adds_nothing(
    tmp_path: Path,
) -> None:
    # Key written ``tmp3``: step 2 keeps it as an alias (origin = source) of Sensor:TMP3.
    pieces = [gauges("TEMP-3", "tmp3"), procedure(("TMP3", "verify.arg0"))]
    a = build(tmp_path, pieces, DOCS, READS, MERGE_TMP3)
    assert aliases(a, "Sensor:TEMP-3") == [("Sensor:TMP3", "proposal"), ("tmp3", "source")]
    assert a.alias_conflicts() == []
    assert reads(a) == ["Sensor:TEMP-3"]
    assert a.mentions == []


def test_a_merged_node_s_key_comes_after_its_own_aliases_in_build_order(tmp_path: Path) -> None:
    # "zz" and "aa" sort after and before "TMP3" in alias order; the key follows both.
    piece = gauges(
        "TEMP-3",
        "TMP3",
        aliases=[Alias("zz", "Row:TMP3", "source"), Alias("aa", "Row:TMP3", "source")],
    )
    a = build(tmp_path, [piece], GAUGES, entries=MERGE_TMP3)
    assert aliases(a, "Sensor:TEMP-3") == [
        ("Sensor:TMP3", "proposal"),
        ("aa", "source"),
        ("zz", "source"),
        ("TMP3", "proposal"),
    ]


def test_a_later_alias_equal_to_a_merged_key_under_nocase_loses_to_it(tmp_path: Path) -> None:
    entries = [*MERGE_TMP3, identity("p2", "Sensor:TEMP-3", ["tmp3"])]
    a = build(tmp_path, [gauges("TEMP-3", "TMP3")], GAUGES, entries=entries)
    (c,) = a.alias_conflicts()
    assert (c.winner.value, c.winner.origin) == ("TMP3", "proposal")
    assert [(g.value, g.piece) for g in c.losers] == [("tmp3", "proposals.yaml")]


def test_a_star_segment_matches_exactly_one_segment(tmp_path: Path) -> None:
    piece = procedure(("T-1", "verify.a"), ("T-2", "verify.a.b"), ("T-3", "check.a"))
    a = build(tmp_path, [gauges("T-1", "T-2", "T-3"), piece], DOCS, READS)
    assert reads(a) == ["Sensor:T-1"]


def test_every_segment_of_the_role_must_match(tmp_path: Path) -> None:
    edges = {"reads": {"from": "Step", "to": "Sensor", "mentions": "*.arg0"}}
    piece = procedure(("T-1", "verify.arg0"), ("T-2", "verify.arg1"), ("T-3", "x.arg0"))
    a = build(tmp_path, [gauges("T-1", "T-2", "T-3"), piece], DOCS, edges)
    assert reads(a) == ["Sensor:T-1", "Sensor:T-3"]


def test_a_mention_s_kind_does_not_change_how_it_matches(tmp_path: Path) -> None:
    name, rows, kwargs = procedure()
    kwargs["mentions"] = [
        Mention("T-1", "line=1", "Step:S1", "verify.a", "identifier"),
        Mention("t-2", "line=2", "Step:S1", "verify.a", "phrase"),
    ]
    a = build(tmp_path, [gauges("T-1", "T-2"), (name, rows, kwargs)], DOCS, READS)
    assert reads(a) == ["Sensor:T-1", "Sensor:T-2"]


def test_an_unmatched_mention_is_reported_and_is_a_stale_reference(tmp_path: Path) -> None:
    a = build(tmp_path, [gauges("T-1"), procedure(("T-9", "verify.arg0"))], DOCS, READS)
    assert a.edge_rows() == []
    assert a.mentions == [
        MentionReport("unmatched", "verify.arg0", "T-9", "proc", "line=1", (), "reads")
    ]
    assert a.stale_references == [StaleReference("T-9", "Sensor", "proc", "line=1")]


def test_a_mention_matching_several_nodes_is_ambiguous_and_makes_no_edge(tmp_path: Path) -> None:
    piece = gauges(
        "T-2",
        "T-1",
        aliases=[Alias("temp", "Row:T-1", "source"), Alias("TEMP", "Row:T-2", "source")],
    )
    a = build(tmp_path, [piece, procedure(("temp", "verify.arg0"))], DOCS, READS)
    assert a.edge_rows() == []
    assert a.mentions == [
        MentionReport(
            "ambiguous", "verify.arg0", "temp", "proc", "line=1", ("Sensor:T-1", "Sensor:T-2"),
            "reads",
        )
    ]  # fmt: skip
    assert a.stale_references == []


def test_a_node_matching_by_key_and_by_alias_counts_once(tmp_path: Path) -> None:
    piece = gauges("T-1", aliases=[Alias("t-1", "Row:T-1", "source")])
    a = build(tmp_path, [piece, procedure(("T-1", "verify.arg0"))], DOCS, READS)
    assert reads(a) == ["Sensor:T-1"]
    assert a.mentions == []


def test_a_mention_whose_node_maps_to_no_from_node_is_skipped_silently(tmp_path: Path) -> None:
    # The step is mapped to Step only from ``proc.Step``; this mention sits on a Note node.
    name, _, kwargs = procedure()
    rows = [node("Step:S1", "S1"), node("Note:N1", "N1")]
    kwargs["mentions"] = [Mention("T-9", "line=1", "Note:N1", "verify.arg0", "phrase")]
    a = build(tmp_path, [gauges("T-1"), (name, rows, kwargs)], DOCS, READS)
    assert (a.edge_rows(), a.mentions, a.stale_references) == ([], [], [])


def test_each_rule_reports_the_mentions_it_cannot_resolve(tmp_path: Path) -> None:
    edges = {
        "reads": {"from": "Step", "to": "Sensor", "mentions": "verify.*"},
        "checks": {"from": "Step", "to": "Sensor", "mentions": "*.arg0"},
    }
    a = build(tmp_path, [gauges("T-1"), procedure(("T-9", "verify.arg0"))], DOCS, edges)
    assert [(m.edge_type, m.status) for m in a.mentions] == [
        ("reads", "unmatched"),
        ("checks", "unmatched"),
    ]
    assert len(a.stale_references) == 2


def test_mention_reports_are_sorted_by_piece_and_locator(tmp_path: Path) -> None:
    piece = procedure(("x", "verify.a"), ("y", "verify.a"), ("z", "verify.a"))
    piece[2]["mentions"] = list(reversed(piece[2]["mentions"]))
    a = build(tmp_path, [gauges("T-1"), piece], DOCS, READS)
    assert [m.locator for m in a.mentions] == ["line=1", "line=2", "line=3"]
    assert [s.locator for s in a.stale_references] == ["line=1", "line=2", "line=3"]


# --- step 5: edge proposals (section 5.5; Q3, Q4) -------------------------------------------

CHAIN = {"Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}}}
FEEDS = {"feeds": {"from": "Sensor", "to": "Sensor", "mentions": "feeds.*"}}


def test_an_accepted_edge_proposal_is_an_extracted_fact_sourced_to_proposals_yaml(
    tmp_path: Path,
) -> None:
    entries = [
        edge_proposal("p1", "feeds", "Sensor:A", "Sensor:B"),
        edge_proposal("p2", "feeds", "Sensor:B", "Sensor:A", decision="open"),
        edge_proposal("p3", "feeds", "Sensor:B", "Sensor:A", decision="rejected"),
    ]
    a = build(tmp_path, [gauges("A", "B")], CHAIN, FEEDS, entries)
    key = EdgeKey("Sensor:A", "feeds", "Sensor:B")
    assert a.edge_rows() == [Edge("feeds", "Sensor:A", "Sensor:B")]
    assert [x for x in a.evidence if x.subject == key] == [
        Evidence(key, "proposals.yaml", "entry=p1", "extracted", "ana")
    ]
    assert a.sources[-1].id == "proposals.yaml"


def test_an_edge_proposal_s_ends_resolve_through_merges(tmp_path: Path) -> None:
    entries = [
        identity("p1", "Sensor:A", ["Sensor:C"]),
        edge_proposal("p2", "feeds", "Sensor:C", "Sensor:B"),
    ]
    a = build(tmp_path, [gauges("A", "B", "C")], CHAIN, FEEDS, entries)
    assert a.edge_rows() == [Edge("feeds", "Sensor:A", "Sensor:B")]


def test_an_edge_proposal_with_an_end_not_in_the_build_no_longer_applies(tmp_path: Path) -> None:
    entries = [
        edge_proposal("p1", "feeds", "Sensor:A", "Sensor:Z"),
        edge_proposal("p2", "feeds", "Sensor:Z", "Sensor:A"),
        edge_proposal("p3", "feeds", "Sensor:Z", "Sensor:Y", decision="open"),
    ]
    a = build(tmp_path, [gauges("A")], CHAIN, FEEDS, entries)
    assert a.edge_rows() == []
    assert statuses(a) == [("p1", "no_longer_applies"), ("p2", "no_longer_applies")]
    assert all(s.id != "proposals.yaml" for s in a.sources)


def test_duplicate_edges_from_map_mentions_and_proposals_are_one_edge(tmp_path: Path) -> None:
    rows = [node("Step:S1", "S1"), node("Row:T-1", "T-1")]
    mentioned = [Mention("T-1", "line=7", "Step:S1", "verify.arg0", "phrase")]
    piece = (
        "proc",
        rows,
        {"edges": [Edge("uses", "Step:S1", "Row:T-1", props='{"n":1}')], "mentions": mentioned},
    )
    types = {
        "Sensor": {"key": "tag", "from": {"proc.Row": {"tag": "key"}}},
        "Step": {"key": "n", "from": {"proc.Step": {"n": "key"}}},
    }
    edges = {
        "reads": {"from": "Step", "to": "Sensor", "map": ["proc.uses"]},
        "mentioned": {"from": "Step", "to": "Sensor", "mentions": "verify.*"},
    }
    # The mention rule makes "mentioned"; the map makes "reads"; the proposal adds to "reads".
    entries = [edge_proposal("p1", "reads", "Step:S1", "Sensor:T-1")]
    a = build(tmp_path, [piece], types, edges, entries)
    key = EdgeKey("Step:S1", "reads", "Sensor:T-1")
    # In build order: map edges, then mention edges, then proposals.
    assert a.edge_rows() == [
        Edge("reads", "Step:S1", "Sensor:T-1", props='{"n": 1}'),
        Edge("mentioned", "Step:S1", "Sensor:T-1"),
    ]
    assert sorted(x.locator for x in a.evidence if x.subject == key) == [
        "entry=p1",
        "file=src.csv;edge=1",
    ]


# --- the whole of steps 1-5 -----------------------------------------------------------------


def test_the_same_inputs_give_the_same_result(tmp_path: Path) -> None:
    entries = [identity("p1", "Sensor:T-1", ["thermo"])]
    pieces = [gauges("T-1"), procedure(("thermo", "verify.a"), ("T-9", "verify.b"))]
    results = []
    for run in ("1", "2"):
        (tmp_path / run).mkdir()
        results.append(build(tmp_path / run, pieces, DOCS, READS, entries))
    one, two = results
    assert one.edge_rows() == two.edge_rows()
    assert one.evidence == two.evidence
    assert (one.mentions, one.stale_references) == (two.mentions, two.stale_references)


def test_the_linked_assembly_seals_into_a_mosaic_the_reading_rules_accept(
    tmp_path: Path,
) -> None:
    entries = [
        identity("p1", "Sensor:T-1", ["thermo"]),
        edge_proposal("p2", "reads", "Step:S1", "Sensor:T-2"),
    ]
    pieces = [gauges("T-1", "T-2"), procedure(("thermo", "verify.a"))]
    a = build(tmp_path, pieces, DOCS, READS, entries)
    content = Content(
        header=Header(kind="mosaic", producer=PRODUCER, pattern_hash="b" * 64, target="t"),
        sources=a.sources,
        types=[
            Type(name="Sensor", kind="node", key_prop="tag"),
            Type(name="Step", kind="node", key_prop="n"),
            Type(name="reads", kind="edge", from_type="Step", to_type="Sensor"),
        ],
        nodes=a.node_rows(),
        edges=a.edge_rows(),
        aliases=a.aliases(),
        evidence=a.evidence,
        external_refs=a.external_refs,
    )
    seal(tmp_path / "out.mosaic", content)
    with mosaic_format.open(tmp_path / "out.mosaic") as m:
        assert m.query("SELECT type, src, dst FROM v_edge ORDER BY dst") == [
            ("reads", "Step:S1", "Sensor:T-1"),
            ("reads", "Step:S1", "Sensor:T-2"),
        ]
