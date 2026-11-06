"""Steps 6-8 of a build: select for the target, derive, seal (Specification 0.1, sections 3.3,
5.4, 7.1 steps 6-8).

Each test names the rule it checks; Q1-Q7 are the maintainer's decisions on #16.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import mosaic_build
import pytest
from mosaic_build.mosaic import BuildError, Built, budget_bytes, build
from mosaic_format.check import check_file
from mosaic_format.file import SIDECARS
from mosaic_format.reader import open as open_sealed
from mosaic_format.writer import (
    Alias,
    Content,
    Edge,
    EdgeKey,
    ExternalRef,
    Header,
    Mention,
    Node,
    Source,
    Type,
)

from tests.mosaic.pieces import (
    edge_proposal,
    evidence,
    mosaic,
    node,
    pattern,
    proposals,
    tessera,
)

type Piece = tuple[str, Sequence[Node], dict[str, Any]]

DEFAULTS = {
    "evidence": "primary",
    "strict": False,
    "text": "snippets",
    "trust": "reviewed",
    "types": "all",
    "vectors": True,
}


def make(
    tmp_path: Path,
    pieces: Sequence[Piece],
    types: dict[str, Any],
    edges: dict[str, Any] | None = None,
    *,
    mosaics: dict[str, Any] | None = None,
    entries: Sequence[dict[str, Any]] | None = None,
    target: str = "default",
    out: str = "out.mosaic",
) -> Built:
    """Seal each piece, write the pattern (and proposals), and build ``target`` into ``out``."""
    paths, listed = [], []
    for name, nodes, kwargs in pieces:
        path = tmp_path / f"{name}.tessera"
        if not path.exists():
            tessera(path, nodes, **kwargs)
        with open_sealed(path) as f:
            listed.append(f"{name}@{f.knowledge_hash}")
        paths.append(path)
    proposals_path = None if entries is None else proposals(tmp_path, entries)
    return build(
        pattern(tmp_path, listed, types, edges, mosaics),
        target,
        tmp_path / out,
        pieces=paths,
        proposals=proposals_path,
    )


def query(built: Built, sql: str, params: Sequence[object] = ()) -> list[tuple[Any, ...]]:
    """Rows of the sealed mosaic, opened by the reading rules (so its hashes are verified)."""
    with open_sealed(built.path) as f:
        return [tuple(r) for r in f.query(sql, tuple(params))]


def header(built: Built) -> dict[str, Any]:
    with open_sealed(built.path) as f:
        cols = [
            "producer",
            "settings",
            "knowledge_hash",
            "vector_hash",
            "embed_model",
            "pattern_hash",
            "target",
        ]
        (row,) = f.query(f"SELECT {', '.join(cols)} FROM header")
        return dict(zip(cols, row, strict=True))


def node_ids(built: Built) -> list[str]:
    return [r[0] for r in query(built, "SELECT id FROM node ORDER BY nid")]


def props(built: Built, node_id: str) -> dict[str, Any]:
    ((text,),) = query(built, "SELECT props FROM node WHERE id = ?", (node_id,))
    return {} if text is None else json.loads(text)


def node_evidence(built: Built, node_id: str) -> list[tuple[Any, ...]]:
    """(prop, source, locator, method, confidence) of a node's evidence, in ``evid`` order."""
    return query(
        built,
        "SELECT prop, source, locator, method, confidence FROM v_evidence WHERE node = ?",
        (node_id,),
    )


def types_declared(built: Built) -> dict[str, tuple[Any, ...]]:
    rows = query(
        built, "SELECT name, kind, description, key_prop, from_type, to_type, props FROM type"
    )
    return {r[0]: (*r[1:6], json.loads(r[6])) for r in rows}


SENSOR = {"Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}}}
"""Sensors keyed by the piece node's key, from piece ``list``."""


def sensors(*keys: str, name: str = "list", **kwargs: Any) -> Piece:
    """A piece of one ``Row`` per key, labelled ``L<key>``."""
    return (name, [node(f"Row:{k}", k, label=f"L{k}") for k in keys], kwargs)


def inferred(subject: str | EdgeKey, locator: str, confidence: float, **kw: Any) -> Any:
    return evidence(subject, locator, method="inferred", confidence=confidence, **kw)


# --- the target (Q7) and the header (Q6, section 3.3) ---------------------------------------


def test_no_mosaics_is_one_target_named_default_with_every_default(tmp_path: Path) -> None:
    built = make(tmp_path, [sensors("A")], SENSOR)
    h = header(built)
    assert h["target"] == "default"
    assert json.loads(h["settings"]) == DEFAULTS
    assert built.target == "default"


def test_an_empty_mosaics_is_one_target_named_default_too(tmp_path: Path) -> None:
    """Section 5.4: a pattern with no targets, `mosaics` absent or `{}`, gets `default`."""
    built = make(tmp_path, [sensors("A")], SENSOR, mosaics={})
    h = header(built)
    assert h["target"] == "default"
    assert json.loads(h["settings"]) == DEFAULTS


def test_undefined_target_fails_with_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(BuildError) as e:
        make(tmp_path, [sensors("A")], SENSOR, target="ops")
    assert e.value.reason == "invalid_input"
    assert "ops" in e.value.message
    assert not (tmp_path / "out.mosaic").exists()


def test_a_pattern_with_mosaics_has_no_default_target(tmp_path: Path) -> None:
    with pytest.raises(BuildError) as e:
        make(tmp_path, [sensors("A")], SENSOR, mosaics={"ops": {}})
    assert e.value.reason == "invalid_input"


def test_settings_are_the_entry_with_defaults_filled_in_as_canonical_json(
    tmp_path: Path,
) -> None:
    mosaics = {"ops": {"trust": 0.5, "budget": "20 MB", "vectors": False}}
    built = make(tmp_path, [sensors("A")], SENSOR, mosaics=mosaics, target="ops")
    expected = {**DEFAULTS, "trust": 0.5, "vectors": False, "budget": "20 MB"}
    assert header(built)["settings"] == json.dumps(expected, sort_keys=True, separators=(",", ":"))
    assert built.settings == header(built)["settings"]


def test_budget_appears_in_settings_only_when_given(tmp_path: Path) -> None:
    built = make(tmp_path, [sensors("A")], SENSOR, mosaics={"ops": {}}, target="ops")
    assert "budget" not in json.loads(header(built)["settings"])


def test_header_names_producer_pattern_hash_and_target(tmp_path: Path) -> None:
    built = make(tmp_path, [sensors("A")], SENSOR)
    h = header(built)
    assert h["producer"] == f"mosaic-build/{mosaic_build.__version__}"
    assert h["pattern_hash"] == hashlib.sha256((tmp_path / "pattern.yaml").read_bytes()).hexdigest()
    assert built.pattern_hash == h["pattern_hash"]
    assert built.knowledge_hash == h["knowledge_hash"]


# --- types (section 5.4) ----------------------------------------------------------------------

SCOPED_TYPES = {
    "Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
    "Unit": {"key": "code", "from": {"list.U": {"code": "key"}}},
    "Plant": {"key": "code", "from": {"list.P": {"code": "key"}}},
}
SCOPED_EDGES = {
    "has_unit": {"from": "Sensor", "to": "Unit", "map": ["list.has_unit"]},
    "in_plant": {"from": "Sensor", "to": "Plant", "map": ["list.in_plant"]},
}


def scoped_piece(**kwargs: Any) -> Piece:
    nodes = [node("Row:A", "A"), node("U:c", "c"), node("P:p1", "p1")]
    edges = [Edge("has_unit", "Row:A", "U:c"), Edge("in_plant", "Row:A", "P:p1")]
    return ("list", nodes, {"edges": edges, **kwargs})


def test_types_keeps_listed_node_types_and_edges_between_them(tmp_path: Path) -> None:
    built = make(
        tmp_path,
        [scoped_piece()],
        SCOPED_TYPES,
        SCOPED_EDGES,
        mosaics={"ops": {"types": ["Sensor", "Unit"]}},
        target="ops",
    )
    assert node_ids(built) == ["Sensor:A", "Unit:c"]
    assert query(built, "SELECT type, src, dst FROM v_edge") == [("has_unit", "Sensor:A", "Unit:c")]
    assert sorted(types_declared(built)) == ["Sensor", "Unit", "has_unit"]


def test_types_all_keeps_every_type(tmp_path: Path) -> None:
    built = make(tmp_path, [scoped_piece()], SCOPED_TYPES, SCOPED_EDGES)
    assert node_ids(built) == ["Plant:p1", "Sensor:A", "Unit:c"]
    assert len(query(built, "SELECT * FROM edge")) == 2


def test_types_in_scope_are_declared_without_rows(tmp_path: Path) -> None:
    # Q1: every node type in scope and every edge type with both ends in scope, rows or not.
    piece = scoped_piece(
        evidence=[
            evidence("Row:A", "row=1"),
            inferred("U:c", "row=2", 0.9),
            evidence("P:p1", "row=3"),
            evidence(EdgeKey("Row:A", "has_unit", "U:c"), "edge=1"),
            evidence(EdgeKey("Row:A", "in_plant", "P:p1"), "edge=2"),
        ]
    )
    built = make(tmp_path, [piece], SCOPED_TYPES, SCOPED_EDGES)
    assert node_ids(built) == ["Plant:p1", "Sensor:A"]
    assert sorted(types_declared(built)) == ["Plant", "Sensor", "Unit", "has_unit", "in_plant"]


# --- trust (section 5.4, section 7.1 step 6, Q3) --------------------------------------------


def test_reviewed_drops_every_inferred_row_and_nodes_left_without_evidence(
    tmp_path: Path,
) -> None:
    piece = sensors(
        "A",
        "B",
        evidence=[
            evidence("Row:A", "row=1"),
            inferred("Row:A", "row=1;field=x", 0.99),
            inferred("Row:B", "row=2", 0.99),
        ],
    )
    built = make(tmp_path, [piece], SENSOR)
    assert node_ids(built) == ["Sensor:A"]
    assert query(built, "SELECT count(*) FROM evidence WHERE method = 'inferred'") == [(0,)]


def test_trust_all_keeps_inferred_rows(tmp_path: Path) -> None:
    piece = sensors("B", evidence=[inferred("Row:B", "row=2", 0.1)])
    built = make(tmp_path, [piece], SENSOR, mosaics={"ops": {"trust": "all"}}, target="ops")
    assert node_evidence(built, "Sensor:B") == [(None, "list/src.csv", "row=2", "inferred", 0.1)]


def test_trust_number_keeps_rows_at_or_above_it(tmp_path: Path) -> None:
    piece = sensors(
        "A",
        "B",
        "C",
        evidence=[
            inferred("Row:A", "row=1", 0.4),
            inferred("Row:B", "row=2", 0.5),
            inferred("Row:C", "row=3", 0.6),
        ],
    )
    built = make(tmp_path, [piece], SENSOR, mosaics={"ops": {"trust": 0.5}}, target="ops")
    assert node_ids(built) == ["Sensor:B", "Sensor:C"]


UNIT = {
    "Sensor": {
        "key": "tag",
        "from": {
            "a.Row": {"tag": "key", "unit": "unit", "range": "range"},
            "b.Row": {"tag": "key", "unit": "unit"},
        },
    }
}


def test_a_dropped_value_neither_wins_nor_is_a_conflict(tmp_path: Path) -> None:
    # Q3: a's unit had evidence on `unit`, all of it inferred; b's value wins, and no conflict.
    a = (
        "a",
        [node("Row:A", "A", unit="F")],
        {
            "evidence": [
                evidence("Row:A", "row=1"),
                inferred("Row:A", "row=1;field=unit", 0.9, prop="unit"),
            ]
        },
    )
    b = (
        "b",
        [node("Row:A", "A", unit="C")],
        {"evidence": [evidence("Row:A", "row=1;field=unit", prop="unit")]},
    )
    built = make(tmp_path, [a, b], UNIT)
    assert props(built, "Sensor:A") == {"unit": "C"}
    assert built.assembly.conflicts() == []


def test_with_trust_all_the_inferred_value_wins_and_conflicts(tmp_path: Path) -> None:
    a = (
        "a",
        [node("Row:A", "A", unit="F")],
        {"evidence": [inferred("Row:A", "row=1;field=unit", 0.9, prop="unit")]},
    )
    b = (
        "b",
        [node("Row:A", "A", unit="C")],
        {"evidence": [evidence("Row:A", "row=1;field=unit", prop="unit")]},
    )
    built = make(tmp_path, [a, b], UNIT, mosaics={"ops": {"trust": "all"}}, target="ops")
    assert props(built, "Sensor:A") == {"unit": "F"}
    (conflict,) = built.assembly.conflicts()
    assert (conflict.property, conflict.winner.value, conflict.losers[0].value) == (
        "unit",
        "F",
        "C",
    )


def test_a_value_with_only_node_level_evidence_survives_trust(tmp_path: Path) -> None:
    # Q3: rows without `prop` are no evidence on a property, so a's unit stays and wins;
    # b's unit had only inferred rows on `unit`, so it is removed and is no conflict.
    a = ("a", [node("Row:A", "A", unit="F")], {"evidence": [evidence("Row:A", "row=1")]})
    b = (
        "b",
        [node("Row:A", "A", unit="C")],
        {"evidence": [inferred("Row:A", "row=1;field=unit", 0.9, prop="unit")]},
    )
    built = make(tmp_path, [a, b], UNIT)
    assert props(built, "Sensor:A") == {"unit": "F"}
    assert built.assembly.conflicts() == []


def test_a_value_with_no_evidence_rows_on_it_survives_trust(tmp_path: Path) -> None:
    # Q3: a's `range` has no rows at all; a's `unit` had only inferred ones. The node stays by
    # b's evidence; `range` stays, a's `unit` goes and b's wins.
    a = (
        "a",
        [node("Row:A", "A", unit="F", range="0-9")],
        {"evidence": [inferred("Row:A", "row=1;field=unit", 0.9, prop="unit")]},
    )
    b = ("b", [node("Row:A", "A", unit="C")], {"evidence": [evidence("Row:A", "row=7")]})
    built = make(tmp_path, [a, b], UNIT)
    assert props(built, "Sensor:A") == {"range": "0-9", "unit": "C"}
    assert node_evidence(built, "Sensor:A") == [(None, "b/src.csv", "row=7", "extracted", None)]


def test_a_value_keeps_while_one_row_on_it_survives(tmp_path: Path) -> None:
    a = (
        "a",
        [node("Row:A", "A", unit="F")],
        {
            "evidence": [
                inferred("Row:A", "row=1;field=unit", 0.9, prop="unit"),
                evidence("Row:A", "row=2;field=unit", prop="unit"),
            ]
        },
    )
    b = ("b", [node("Row:A", "A", unit="C")], {})
    built = make(tmp_path, [a, b], UNIT)
    assert props(built, "Sensor:A") == {"unit": "F"}
    assert [c.property for c in built.assembly.conflicts()] == ["unit"]


def test_label_follows_its_evidence_too(tmp_path: Path) -> None:
    types = {
        "Sensor": {
            "key": "tag",
            "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}},
        }
    }
    a = (
        "a",
        [node("Row:A", "A", label="guess")],
        {
            "evidence": [
                evidence("Row:A", "row=1"),
                inferred("Row:A", "row=1;field=label", 0.8, prop="label"),
            ]
        },
    )
    b = ("b", [node("Row:A", "A", label="Sensor A")], {})
    built = make(tmp_path, [a, b], types)
    assert query(built, "SELECT label FROM node") == [("Sensor A",)]
    assert built.assembly.conflicts() == []


def test_a_node_without_evidence_left_goes_with_its_edges_aliases_and_refs(
    tmp_path: Path,
) -> None:
    nodes = [node("Row:A", "A"), node("U:c", "c")]
    piece = (
        "list",
        nodes,
        {
            "edges": [Edge("has_unit", "Row:A", "U:c")],
            "aliases": [Alias("cee", "U:c", "source")],
            "external_refs": [
                ExternalRef("U:c", "plm", "document", '{"doc":"1"}', "src.csv"),
            ],
            "evidence": [
                evidence("Row:A", "row=1"),
                inferred("U:c", "row=2", 0.9),
                evidence(EdgeKey("Row:A", "has_unit", "U:c"), "edge=1"),
            ],
        },
    )
    types = {
        "Sensor": SCOPED_TYPES["Sensor"],
        "Unit": SCOPED_TYPES["Unit"],
    }
    built = make(tmp_path, [piece], types, {"has_unit": SCOPED_EDGES["has_unit"]})
    assert node_ids(built) == ["Sensor:A"]
    assert query(built, "SELECT count(*) FROM edge") == [(0,)]
    assert query(built, "SELECT count(*) FROM alias") == [(0,)]
    assert query(built, "SELECT count(*) FROM external_ref") == [(0,)]
    assert query(built, "SELECT count(*) FROM link_count") == [(0,)]


def test_an_edge_without_evidence_left_goes(tmp_path: Path) -> None:
    piece = scoped_piece(
        evidence=[
            evidence("Row:A", "row=1"),
            evidence("U:c", "row=2"),
            evidence("P:p1", "row=3"),
            inferred(EdgeKey("Row:A", "has_unit", "U:c"), "edge=1", 0.9),
            evidence(EdgeKey("Row:A", "in_plant", "P:p1"), "edge=2"),
        ]
    )
    built = make(tmp_path, [piece], SCOPED_TYPES, SCOPED_EDGES)
    assert query(built, "SELECT type FROM v_edge") == [("in_plant",)]


def test_an_edge_value_follows_its_evidence(tmp_path: Path) -> None:
    types = {
        "Sensor": {"key": "tag", "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}}},
        "Unit": {"key": "code", "from": {"a.U": {"code": "key"}, "b.U": {"code": "key"}}},
    }
    edges = {"has_unit": {"from": "Sensor", "to": "Unit", "map": ["a.has_unit", "b.has_unit"]}}
    key = EdgeKey("Row:A", "has_unit", "U:c")
    nodes = [node("Row:A", "A"), node("U:c", "c")]
    a = (
        "a",
        nodes,
        {
            "edges": [Edge("has_unit", "Row:A", "U:c", props='{"w":1}')],
            "evidence": [
                evidence("Row:A", "row=1"),
                evidence("U:c", "row=2"),
                evidence(key, "edge=1"),
                inferred(key, "edge=1;field=w", 0.9, prop="w"),
            ],
        },
    )
    b = ("b", nodes, {"edges": [Edge("has_unit", "Row:A", "U:c", props='{"w":2}')]})
    built = make(tmp_path, [a, b], types, edges)
    assert query(built, "SELECT props FROM edge") == [('{"w":2}',)]
    assert built.assembly.edge_conflicts() == []


# --- evidence (section 5.4, Q2) ---------------------------------------------------------------

LABELLED = {"Sensor": {"key": "tag", "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}}}}


def two_pieces() -> list[Piece]:
    rows = [node("Row:A", "A", label="LA")]
    a = (
        "a",
        rows,
        {
            "evidence": [
                evidence("Row:A", "row=2"),
                evidence("Row:A", "row=10"),
                evidence("Row:A", "row=2;field=label", prop="label", snippet="LA"),
            ]
        },
    )
    b = (
        "b",
        rows,
        {
            "evidence": [
                evidence("Row:A", "row=1"),
                evidence("Row:A", "row=1;field=label", prop="label"),
            ]
        },
    )
    return [a, b]


def test_primary_keeps_one_row_per_fact_from_the_earliest_piece(tmp_path: Path) -> None:
    # Q2: a fact is a subject and one `prop`; a row without `prop` is a fact of its own. Within
    # piece a, the tie goes to the first row in canonical order: locator "row=10" < "row=2".
    built = make(tmp_path, two_pieces(), LABELLED)
    assert node_evidence(built, "Sensor:A") == [
        (None, "a/src.csv", "row=10", "extracted", None),
        ("label", "a/src.csv", "row=2;field=label", "extracted", None),
    ]


def test_primary_tie_breaks_by_source_before_locator(tmp_path: Path) -> None:
    # Q2: canonical order is (sid, locator, ...), and sid ranks the source ids. A tessera has
    # one source, so a piece with two is a mosaic piece.
    path = tmp_path / "two.mosaic"
    two = Content(
        header=Header(kind="mosaic", producer="t/1", pattern_hash="c" * 64, target="t"),
        sources=[
            Source(id="p", kind="tessera", hash="d" * 64),
            Source(id="p/b.csv", kind="file", hash="b" * 64),
            Source(id="p/a.csv", kind="file", hash="a" * 64),
        ],
        types=[Type(name="Row", kind="node", key_prop="k")],
        nodes=[node("Row:A", "A")],
        evidence=[
            evidence("Row:A", "row=1", source="p/b.csv"),
            evidence("Row:A", "row=9", source="p/a.csv"),
        ],
    )
    h = mosaic(path, two)
    built = build(
        pattern(tmp_path, [f"two@{h}"], {"Thing": {"key": "k", "from": {"two.Row": {"k": "key"}}}}),
        "default",
        tmp_path / "out.mosaic",
        pieces=[path],
    )
    assert node_evidence(built, "Thing:A") == [(None, "two/p/a.csv", "row=9", "extracted", None)]


def test_evidence_all_keeps_every_row(tmp_path: Path) -> None:
    built = make(
        tmp_path, two_pieces(), LABELLED, mosaics={"ops": {"evidence": "all"}}, target="ops"
    )
    assert len(node_evidence(built, "Sensor:A")) == 5


def test_trust_is_applied_before_primary(tmp_path: Path) -> None:
    # Q2: an inferred row dropped by trust cannot hide an extracted row from a later piece.
    rows = [node("Row:A", "A")]
    a = ("a", rows, {"evidence": [inferred("Row:A", "row=1", 0.9)]})
    b = ("b", rows, {"evidence": [evidence("Row:A", "row=5")]})
    built = make(tmp_path, [a, b], LABELLED)
    assert node_evidence(built, "Sensor:A") == [(None, "b/src.csv", "row=5", "extracted", None)]


MENTIONED = {
    "Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
    "Step": {"key": "id", "from": {"procs.St": {"id": "key"}, "more.St": {"id": "key"}}},
}
VERIFIES = {"verifies": {"from": "Step", "to": "Sensor", "mentions": "verify.*"}}


def mentioning(name: str, line: int) -> Piece:
    return (
        name,
        [node("St:S1", "S1")],
        {"mentions": [Mention("A", f"line={line}", "St:S1", "verify.arg", "identifier")]},
    )


def test_primary_mention_row_has_its_piece_priority_and_proposals_come_last(
    tmp_path: Path,
) -> None:
    # Q2: a mention row has the priority of the piece holding the mention, and
    # `proposals.yaml` comes after every piece.
    entries = [edge_proposal("p1", "verifies", "Step:S1", "Sensor:A")]
    pieces = [sensors("A"), mentioning("procs", 9), mentioning("more", 1)]
    built = make(tmp_path, pieces, MENTIONED, VERIFIES, entries=entries)
    assert query(built, "SELECT source, locator FROM v_evidence WHERE edge_type = 'verifies'") == [
        ("procs/src.csv", "line=9")
    ]


def test_evidence_all_keeps_mention_and_proposal_rows(tmp_path: Path) -> None:
    entries = [edge_proposal("p1", "verifies", "Step:S1", "Sensor:A")]
    pieces = [sensors("A"), mentioning("procs", 9), mentioning("more", 1)]
    built = make(
        tmp_path,
        pieces,
        MENTIONED,
        VERIFIES,
        entries=entries,
        mosaics={"ops": {"evidence": "all"}},
        target="ops",
    )
    rows = query(built, "SELECT source FROM v_evidence WHERE edge_type = 'verifies'")
    assert sorted(r[0] for r in rows) == ["more/src.csv", "procs/src.csv", "proposals.yaml"]


# --- text (section 5.4) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "snippets", "texts"),
    [("none", 0, 0), ("snippets", 1, 0), ("full", 1, 1)],
)
def test_text_tier(tmp_path: Path, tier: str, snippets: int, texts: int) -> None:
    piece = sensors(
        "A",
        text="tag A reads\n",
        evidence=[evidence("Row:A", "row=1", snippet="tag A reads")],
    )
    built = make(tmp_path, [piece], SENSOR, mosaics={"ops": {"text": tier}}, target="ops")
    assert query(built, "SELECT count(*) FROM snippet") == [(snippets,)]
    assert query(built, "SELECT count(*) FROM source_text") == [(texts,)]
    # `search` is contentless (format.sql): a snippet is indexed when a phrase in it matches.
    found = query(built, "SELECT rowid FROM search WHERE search MATCH 'snippets:reads'")
    assert found == ([(1,)] if snippets else [])
    # Sources stay whole whatever the tier.
    assert query(built, "SELECT id FROM source ORDER BY sid") == [("list",), ("list/src.csv",)]


def test_sources_stay_whole_when_nothing_cites_them(tmp_path: Path) -> None:
    other = ("other", [node("Row:Z", "Z")], {"source": "other.csv"})
    types = {
        "Sensor": SENSOR["Sensor"],
        "Thing": {"key": "k", "from": {"other.Row": {"k": "key"}}},
    }
    built = make(
        tmp_path,
        [sensors("A"), other],
        types,
        mosaics={"ops": {"types": ["Sensor"]}},
        target="ops",
    )
    assert node_ids(built) == ["Sensor:A"]
    assert [r[0] for r in query(built, "SELECT id FROM source ORDER BY sid")] == [
        "list",
        "list/src.csv",
        "other",
        "other/other.csv",
    ]


# --- vectors (Q5) -----------------------------------------------------------------------------


def test_vectors_true_is_skipped_with_a_message(tmp_path: Path) -> None:
    built = make(tmp_path, [sensors("A")], SENSOR)
    assert built.messages == ("vectors skipped, not yet implemented",)
    h = header(built)
    assert (h["vector_hash"], h["embed_model"]) == (None, None)
    assert built.vector_hash is None
    assert query(built, "SELECT count(*) FROM vector") == [(0,)]


def test_vectors_false_has_no_message(tmp_path: Path) -> None:
    built = make(
        tmp_path, [sensors("A")], SENSOR, mosaics={"ops": {"vectors": False}}, target="ops"
    )
    assert built.messages == ()


# --- budget (Q4) ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("20 MB", 20_000_000),
        ("1 KB", 1_000),
        ("1.5 KB", 1_500),
        ("1.0005 KB", 1_000),
        ("2GB", 2_000_000_000),
        ("7 B", 7),
        ("0.5 B", 0),
        ("0.1 GB", 100_000_000),
    ],
)
def test_budget_is_decimal_and_rounds_down(text: str, size: int) -> None:
    assert budget_bytes(text) == size


def test_over_budget_build_leaves_no_file(tmp_path: Path) -> None:
    with pytest.raises(BuildError) as e:
        make(tmp_path, [sensors("A")], SENSOR, mosaics={"ops": {"budget": "1 KB"}}, target="ops")
    assert e.value.reason == "over_budget"
    out = tmp_path / "out.mosaic"
    assert not out.exists()
    assert not any(out.with_name(out.name + s).exists() for s in SIDECARS)


def test_budget_compares_with_the_sealed_file_size(tmp_path: Path) -> None:
    first = make(tmp_path, [sensors("A")], SENSOR, out="first.mosaic")
    size = first.path.stat().st_size
    assert first.file_size == size
    at = make(
        tmp_path,
        [sensors("A")],
        SENSOR,
        mosaics={"ops": {"budget": f"{size} B"}},
        target="ops",
        out="at.mosaic",
    )
    assert at.file_size == size
    with pytest.raises(BuildError) as e:
        make(
            tmp_path,
            [sensors("A")],
            SENSOR,
            mosaics={"ops": {"budget": f"{size - 1} B"}},
            target="ops",
            out="under.mosaic",
        )
    assert e.value.reason == "over_budget"
    assert not (tmp_path / "under.mosaic").exists()


# --- derive: declared types (Q1, section 7.1 step 7) ------------------------------------------


def test_types_declare_description_key_prop_and_kinds(tmp_path: Path) -> None:
    types = {
        "Sensor": {
            "key": "tag",
            "describe": "A measuring point",
            "from": {
                "a.Row": {"tag": "key", "unit": "u", "range": "r", "extra": "x", "label": "t"},
                "b.Item": {"tag": "key", "unit": "unit", "note": "note"},
            },
        },
        "Unit": {"key": "code", "from": {"a.U": {"code": "key"}}},
    }
    edges = {
        "has_unit": {
            "from": "Sensor",
            "to": "Unit",
            "describe": "Unit a sensor reads in",
            "map": ["b.has_unit", "a.has_unit"],
        },
        "near": {"from": "Sensor", "to": "Sensor", "mentions": "near.*"},
    }
    a = (
        "a",
        [node("Row:A", "A", u="C", r=3, x=[1], t="Sensor A"), node("U:c", "c")],
        {
            "edges": [Edge("has_unit", "Row:A", "U:c", props='{"w":1,"z":true}')],
            "declared": {
                "Row": {"u": "text", "r": "integer", "t": "text"},
                "has_unit": {"w": "number"},
            },
        },
    )
    b = (
        "b",
        [node("Item:A", "A", unit=1, note=True), node("U:c", "c")],
        {
            "edges": [Edge("has_unit", "Item:A", "U:c")],
            "declared": {
                "Item": {"unit": "integer", "note": "boolean"},
                "has_unit": {"w": "integer", "q": "text"},
            },
        },
    )
    built = make(tmp_path, [a, b], types, edges)
    declared = types_declared(built)
    assert declared["Sensor"] == (
        "node",
        "A measuring point",
        "tag",
        None,
        None,
        {"unit": "text", "range": "integer", "note": "boolean", "extra": "json"},
    )
    assert declared["Unit"] == ("node", None, "code", None, None, {})
    # `map` lists b first, but piece a comes first in `pieces`, so a's kind of `w` wins.
    assert declared["has_unit"] == (
        "edge",
        "Unit a sensor reads in",
        None,
        "Sensor",
        "Unit",
        {"w": "number", "q": "text", "z": "json"},
    )
    assert declared["near"] == ("edge", None, None, "Sensor", "Sensor", {})


def test_proposal_only_edge_type_declares_no_props(tmp_path: Path) -> None:
    types = {
        "Sensor": SENSOR["Sensor"],
        "Step": {"key": "id", "from": {"procs.St": {"id": "key"}}},
    }
    edges = {"verifies": {"from": "Step", "to": "Sensor", "mentions": "verify.*"}}
    entries = [edge_proposal("p1", "verifies", "Step:S1", "Sensor:A")]
    built = make(
        tmp_path,
        [sensors("A"), ("procs", [node("St:S1", "S1")], {})],
        types,
        edges,
        entries=entries,
    )
    assert types_declared(built)["verifies"][5] == {}
    assert query(built, "SELECT type, src, dst FROM v_edge") == [
        ("verifies", "Step:S1", "Sensor:A")
    ]


# --- seal: the result passes the checker, deterministically -----------------------------------


def rich(tmp_path: Path, out: str = "out.mosaic") -> Built:
    pieces = [
        sensors(
            "A",
            "B",
            aliases=[Alias("ay", "Row:A", "source")],
            external_refs=[ExternalRef("Row:A", "historian", "timeseries", '{"s":"A"}', "src.csv")],
            evidence=[
                evidence("Row:A", "row=1", snippet="A is a sensor"),
                evidence("Row:B", "row=2"),
                inferred("Row:B", "row=2;field=label", 0.7, prop="label"),
            ],
            text="A is a sensor\nB is one too\n",
        ),
        mentioning("procs", 3),
    ]
    entries = [edge_proposal("p1", "verifies", "Step:S1", "Sensor:B")]
    types = {
        "Sensor": SENSOR["Sensor"],
        "Step": {"key": "id", "from": {"procs.St": {"id": "key"}}},
    }
    return make(
        tmp_path,
        pieces,
        types,
        VERIFIES,
        entries=entries,
        mosaics={"ops": {"text": "full", "vectors": False}},
        target="ops",
        out=out,
    )


def test_built_mosaic_passes_check_file(tmp_path: Path) -> None:
    built = rich(tmp_path)
    report = check_file(built.path, pieces=[tmp_path / "list.tessera", tmp_path / "procs.tessera"])
    assert report.ok, report.violations
    assert query(built, "SELECT type, src, dst FROM v_edge") == [
        ("verifies", "Step:S1", "Sensor:A"),
        ("verifies", "Step:S1", "Sensor:B"),
    ]
    assert query(
        built,
        "SELECT n.id, l.type, l.direction, l.count FROM link_count AS l"
        " JOIN node AS n USING (nid) ORDER BY n.id, l.direction",
    ) == [
        ("Sensor:A", "verifies", "in", 1),
        ("Sensor:B", "verifies", "in", 1),
        ("Step:S1", "verifies", "out", 2),
    ]


def test_same_inputs_give_the_same_knowledge_hash(tmp_path: Path) -> None:
    first = rich(tmp_path, "first.mosaic")
    second = rich(tmp_path, "second.mosaic")
    assert first.knowledge_hash == second.knowledge_hash
    assert first.path.read_bytes() == second.path.read_bytes()


def test_evidence_through_a_mosaic_piece_has_via_and_passes_check_file(tmp_path: Path) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    first = make(
        inner, [sensors("A")], SENSOR, mosaics={"plant": {"vectors": False}}, target="plant"
    )
    outer = tmp_path / "outer"
    outer.mkdir()
    built = build(
        pattern(
            outer,
            [{"name": "plant", "hash": first.knowledge_hash, "kind": "mosaic"}],
            {"Gauge": {"key": "tag", "from": {"plant.Sensor": {"tag": "key"}}}},
        ),
        "default",
        outer / "out.mosaic",
        pieces=[first.path],
    )
    assert query(built, "SELECT via FROM evidence") == [(json.dumps([first.knowledge_hash]),)]
    report = check_file(built.path, pieces=[first.path])
    assert report.ok, report.violations
