"""The build report and strict mode (Specification 0.1, sections 7.2 and 7.3; #17).

Every build writes ``build-report.json`` beside the mosaic, also when it fails, valid against
``spec/build-report.schema.json``. Q1-Q6 are the maintainer's decisions on #17; the byte format
(key order, indent, line endings) is the builder convention recorded there.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mosaic_build.mosaic import BuildError, Built, build
from mosaic_format.file import SIDECARS
from mosaic_format.writer import Alias, Content, Edge, Header, Mention, Source, Type

from tests.conftest import SPEC
from tests.mosaic.pieces import (
    edge_proposal,
    evidence,
    identity,
    mosaic,
    node,
    pattern,
    proposals,
    tessera,
)

type Piece = tuple[str, Sequence[Any], dict[str, Any]]

SCHEMA = json.loads((SPEC / "build-report.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
REPORT = "build-report.json"


def run(
    directory: Path,
    pieces: Sequence[Piece],
    types: dict[str, Any],
    edges: dict[str, Any] | None = None,
    *,
    mosaics: dict[str, Any] | None = None,
    entries: Sequence[dict[str, Any]] | None = None,
    target: str = "default",
    out: str = "out/out.mosaic",
) -> tuple[Built | BuildError, dict[str, Any]]:
    """Seal the pieces, write the pattern, build ``target``; return the result and the report.

    The mosaic goes to ``out`` (in a subdirectory, so the report's place is tested); the report
    is checked against the schema before it is returned.
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths, listed = [], []
    for name, nodes, kwargs in pieces:
        path = directory / f"{name}.tessera"
        listed.append(f"{name}@{tessera(path, nodes, **kwargs)}")
        paths.append(path)
    proposals_path = None if entries is None else proposals(directory, entries)
    result: Built | BuildError
    try:
        result = build(
            pattern(directory, listed, types, edges, mosaics),
            target,
            directory / out,
            pieces=paths,
            proposals=proposals_path,
        )
    except BuildError as e:
        result = e
    report = load(directory / out)
    return result, report


def load(out: Path) -> dict[str, Any]:
    path = out.parent / REPORT
    data = json.loads(path.read_bytes().decode("utf-8"))
    errors = [e.message for e in VALIDATOR.iter_errors(data)]
    assert errors == [], errors
    return data


def strict(**fields: Any) -> dict[str, Any]:
    return {"ops": {"strict": True, "vectors": False, **fields}}


SENSOR = {"Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}}}
"""Sensors keyed by the piece node's key, from piece ``list``."""

NATURAL: dict[str, Any] = {"key_props": {"Row": "tag"}}
"""A ``list`` piece whose ``Row`` type has a natural key (``key_prop`` set)."""


def sensors(*keys: str, name: str = "list", **kwargs: Any) -> Piece:
    """A piece of one ``Row`` per key, labelled ``L<key>``."""
    return (name, [node(f"Row:{k}", k, label=f"L{k}") for k in keys], kwargs)


UNIT = {
    "Sensor": {
        "key": "tag",
        "from": {"a.Row": {"tag": "key", "unit": "unit"}, "b.Row": {"tag": "key", "unit": "unit"}},
    }
}


def units(a: str, b: str, *, label_b: str = "LA") -> list[Piece]:
    """Two pieces giving ``Sensor:A`` the units ``a`` and ``b``."""
    return [
        ("a", [node("Row:A", "A", label="LA", unit=a)], {}),
        ("b", [node("Row:A", "A", label=label_b, unit=b)], {"source_hash": "b" * 64}),
    ]


DOCS = {
    "Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
    "Step": {"key": "n", "from": {"proc.Step": {"n": "key"}}},
}
READS = {"reads": {"from": "Step", "to": "Sensor", "mentions": "verify.*"}}


def procedure(*mentions: tuple[str, str], **kwargs: Any) -> Piece:
    """Piece ``proc``: one step ``S1`` that mentions each ``(text, role)``."""
    found = [
        Mention(text, f"line={i + 1}", "Step:S1", role, "phrase")
        for i, (text, role) in enumerate(mentions)
    ]
    return ("proc", [node("Step:S1", "S1")], {"source": "proc.txt", "mentions": found, **kwargs})


# --- the five reports of "Done when": valid and byte-identical across two runs ---------------


def _clean(d: Path) -> tuple[Built | BuildError, dict[str, Any]]:
    return run(d, [sensors("A", "B", **NATURAL)], SENSOR)


def _conflicting(d: Path) -> tuple[Built | BuildError, dict[str, Any]]:
    return run(d, units("°F", "°C"), UNIT)


def _strict(d: Path) -> tuple[Built | BuildError, dict[str, Any]]:
    return run(d, units("°F", "°C"), UNIT, mosaics=strict(), target="ops")


def _over_budget(d: Path) -> tuple[Built | BuildError, dict[str, Any]]:
    return run(d, [sensors("A")], SENSOR, mosaics={"ops": {"budget": "1 KB"}}, target="ops")


def _invalid(d: Path) -> tuple[Built | BuildError, dict[str, Any]]:
    return run(d, [sensors("A")], SENSOR, target="nowhere")


@pytest.mark.parametrize(
    ("make", "outcome", "reason"),
    [
        (_clean, "built", None),
        (_conflicting, "built", None),
        (_strict, "failed", "strict"),
        (_over_budget, "failed", "over_budget"),
        (_invalid, "failed", "invalid_input"),
    ],
    ids=["clean", "conflicting", "strict", "over_budget", "invalid_input"],
)
def test_reports_validate_and_are_byte_identical_across_two_runs(
    tmp_path: Path, make: Any, outcome: str, reason: str | None
) -> None:
    first, report = make(tmp_path / "one")
    second, _ = make(tmp_path / "two")
    assert (report["outcome"], report["reason"]) == (outcome, reason)
    if reason is not None:
        assert isinstance(first, BuildError) and first.reason == reason
        assert isinstance(second, BuildError)
    one = (tmp_path / "one" / "out" / REPORT).read_bytes()
    two = (tmp_path / "two" / "out" / REPORT).read_bytes()
    assert one == two


def test_a_clean_build_reports_its_hashes_size_and_counts(tmp_path: Path) -> None:
    built, report = _clean(tmp_path)
    assert isinstance(built, Built)
    pattern_hash = hashlib.sha256((tmp_path / "pattern.yaml").read_bytes()).hexdigest()
    assert report == {
        "format": "0.1",
        "outcome": "built",
        "reason": None,
        "target": "default",
        "pattern_hash": pattern_hash,
        "knowledge_hash": built.knowledge_hash,
        "vector_hash": None,
        "file_size": built.path.stat().st_size,
        "counts": {"nodes": {"Sensor": 2}, "edges": {}},
        "conflicts": [],
        "alias_conflicts": [],
        "stale_references": [],
        "mentions": [],
        "weak_ids": [],
        "proposals": [],
        "notices": [],
    }
    assert built.report == tmp_path / "out" / REPORT


def test_the_report_sits_beside_the_mosaic_also_on_failure(tmp_path: Path) -> None:
    failed, _ = _invalid(tmp_path)
    assert isinstance(failed, BuildError)
    assert failed.report == tmp_path / "out" / REPORT
    assert failed.report.is_file()
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [REPORT]


# --- conflicts (sections 7.2 and 7.3) -------------------------------------------------------


def test_a_conflict_lists_node_property_winner_and_losers(tmp_path: Path) -> None:
    _, report = _conflicting(tmp_path)
    assert report["conflicts"] == [
        {
            "node": "Sensor:A",
            "property": "unit",
            "winner": {"value": "°F", "piece": "a"},
            "losers": [{"value": "°C", "piece": "b"}],
        }
    ]


def test_a_conflict_value_is_the_json_value_itself(tmp_path: Path) -> None:
    pieces = [
        ("a", [node("Row:A", "A", unit=3)], {}),
        ("b", [node("Row:A", "A", unit={"si": [1.5, None]})], {}),
    ]
    _, report = run(tmp_path, pieces, UNIT)
    (conflict,) = report["conflicts"]
    assert conflict["winner"] == {"value": 3, "piece": "a"}
    assert conflict["losers"] == [{"value": {"si": [1.5, None]}, "piece": "b"}]


def test_label_and_summary_clashes_are_listed_only_for_a_strict_target(tmp_path: Path) -> None:
    pieces = units("°F", "°F", label_b="Other")
    _, plain = run(tmp_path / "plain", pieces, UNIT)
    assert plain["conflicts"] == []
    failed, report = run(tmp_path / "strict", pieces, UNIT, mosaics=strict(), target="ops")
    assert isinstance(failed, BuildError) and failed.reason == "strict"
    assert [(c["node"], c["property"]) for c in report["conflicts"]] == [("Sensor:A", "label")]


def test_an_edge_conflict_names_the_edge(tmp_path: Path) -> None:
    types = {
        "Sensor": {"key": "tag", "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}}},
        "Unit": {"key": "u", "from": {"a.U": {"u": "key"}, "b.U": {"u": "key"}}},
    }
    edges = {"measured_in": {"from": "Sensor", "to": "Unit", "map": ["a.in", "b.in"]}}

    def piece(name: str, scale: int) -> Piece:
        rows = [node("Row:A", "A"), node("U:v", "v")]
        return (name, rows, {"edges": [Edge("in", "Row:A", "U:v", "x", json.dumps({"s": scale}))]})

    _, report = run(tmp_path, [piece("a", 1), piece("b", 2)], types, edges)
    assert report["conflicts"] == [
        {
            "edge": {"type": "measured_in", "from": "Sensor:A", "to": "Unit:v", "qualifier": "x"},
            "property": "s",
            "winner": {"value": 1, "piece": "a"},
            "losers": [{"value": 2, "piece": "b"}],
        }
    ]
    assert report["counts"]["edges"] == {"measured_in": 1}


def test_alias_conflicts_list_kept_and_lost_spellings(tmp_path: Path) -> None:
    pieces = [
        sensors("A", name="a", aliases=[Alias("temp", "Row:A", "source")]),
        sensors("A", name="b", aliases=[Alias("TEMP", "Row:A", "source")]),
    ]
    types = {"Sensor": {"key": "tag", "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}}}}
    _, report = run(tmp_path, pieces, types)
    assert report["alias_conflicts"] == [
        {
            "node": "Sensor:A",
            "winner": {"value": "temp", "piece": "a"},
            "losers": [{"value": "TEMP", "piece": "b"}],
        }
    ]


# --- strict mode (section 7.3; Q2) ------------------------------------------------------------


def test_strict_fails_on_a_conflict_writes_the_report_and_no_mosaic(tmp_path: Path) -> None:
    failed, report = _strict(tmp_path)
    assert isinstance(failed, BuildError) and failed.reason == "strict"
    out = tmp_path / "out" / "out.mosaic"
    assert not out.exists()
    assert not any(out.with_name(out.name + s).exists() for s in SIDECARS)
    assert (report["knowledge_hash"], report["vector_hash"], report["file_size"]) == (
        None,
        None,
        None,
    )
    assert report["pattern_hash"] is not None
    assert report["counts"] == {"nodes": {"Sensor": 1}, "edges": {}}
    assert [c["property"] for c in report["conflicts"]] == ["unit"]


def test_strict_fails_on_an_alias_conflict(tmp_path: Path) -> None:
    pieces = [
        sensors("A", name="a", aliases=[Alias("temp", "Row:A", "source")]),
        sensors("A", name="b", aliases=[Alias("TEMP", "Row:A", "source")]),
    ]
    types = {"Sensor": {"key": "tag", "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}}}}
    failed, report = run(tmp_path, pieces, types, mosaics=strict(), target="ops")
    assert isinstance(failed, BuildError) and failed.reason == "strict"
    assert len(report["alias_conflicts"]) == 1


def test_strict_fails_on_an_unmatched_mention_but_not_an_ambiguous_one(tmp_path: Path) -> None:
    unmatched = [sensors("T-1"), procedure(("T-9", "verify.arg0"))]
    failed, report = run(tmp_path / "u", unmatched, DOCS, READS, mosaics=strict(), target="ops")
    assert isinstance(failed, BuildError) and failed.reason == "strict"
    assert [m["status"] for m in report["mentions"]] == ["unmatched"]
    assert report["stale_references"] == [
        {"name": "T-9", "type": "Sensor", "piece": "proc", "locator": "line=1"}
    ]

    aliases = [Alias("temp", "Row:T-1", "source"), Alias("TEMP", "Row:T-2", "source")]
    ambiguous = [sensors("T-1", "T-2", aliases=aliases), procedure(("temp", "verify.arg0"))]
    built, report = run(tmp_path / "a", ambiguous, DOCS, READS, mosaics=strict(), target="ops")
    assert isinstance(built, Built)
    assert report["mentions"] == [
        {
            "status": "ambiguous",
            "role": "verify.arg0",
            "text": "temp",
            "piece": "proc",
            "locator": "line=1",
            "candidates": ["Sensor:T-1", "Sensor:T-2"],
        }
    ]


def test_a_strict_target_without_problems_builds(tmp_path: Path) -> None:
    built, report = run(tmp_path, units("°F", "°F"), UNIT, mosaics=strict(), target="ops")
    assert isinstance(built, Built)
    assert report["outcome"] == "built"


def test_strict_wins_over_over_budget(tmp_path: Path) -> None:
    failed, report = run(
        tmp_path, units("°F", "°C"), UNIT, mosaics=strict(budget="1 B"), target="ops"
    )
    assert isinstance(failed, BuildError) and failed.reason == "strict"
    assert report["reason"] == "strict"
    assert report["file_size"] is None


RENAMED = {
    "Sensor": {
        "key": "tag",
        "from": {"a.Row": {"tag": "key", "u": "unit"}, "b.Row": {"tag": "key", "u": "unit"}},
    }
}
"""``UNIT`` with the piece field ``unit`` mapped to the property ``u``."""


# --- failed reports (Q2) ------------------------------------------------------------------------


def test_over_budget_reports_the_removed_file_with_counts_and_lists(tmp_path: Path) -> None:
    failed, report = run(
        tmp_path,
        [("a", [node("Row:A", "A", unit="F")], {}), ("b", [node("Row:A", "A", unit="C")], {})],
        RENAMED,
        mosaics={"ops": {"budget": "1 KB", "vectors": False}},
        target="ops",
    )
    assert isinstance(failed, BuildError) and failed.reason == "over_budget"
    assert not (tmp_path / "out" / "out.mosaic").exists()
    assert report["knowledge_hash"] is not None
    assert report["file_size"] is not None and report["file_size"] > 1000
    assert report["counts"] == {"nodes": {"Sensor": 1}, "edges": {}}
    assert [c["property"] for c in report["conflicts"]] == ["u"]
    assert report["weak_ids"] == [{"type": "Sensor", "count": 1}]


EMPTY = {
    "knowledge_hash": None,
    "vector_hash": None,
    "file_size": None,
    "counts": {"nodes": {}, "edges": {}},
    "conflicts": [],
    "alias_conflicts": [],
    "stale_references": [],
    "mentions": [],
    "weak_ids": [],
    "proposals": [],
    "notices": [],
}


def test_a_step_1_failure_has_the_pattern_hash_and_nothing_else(tmp_path: Path) -> None:
    failed, report = run(tmp_path, [sensors("A", notice="CC-BY")], SENSOR, target="nowhere")
    assert isinstance(failed, BuildError) and failed.reason == "invalid_input"
    pattern_hash = hashlib.sha256((tmp_path / "pattern.yaml").read_bytes()).hexdigest()
    assert report == {
        "format": "0.1",
        "outcome": "failed",
        "reason": "invalid_input",
        "target": "nowhere",
        "pattern_hash": pattern_hash,
        **EMPTY,
    }


def test_a_piece_mismatch_is_reported(tmp_path: Path) -> None:
    tessera(tmp_path / "list.tessera", [node("Row:A", "A")])
    out = tmp_path / "out" / "out.mosaic"
    with pytest.raises(BuildError) as e:
        build(
            pattern(tmp_path, ["list@" + "0" * 64], SENSOR),
            "default",
            out,
            pieces=[tmp_path / "list.tessera"],
        )
    assert e.value.reason == "piece_mismatch"
    report = load(out)
    assert (report["outcome"], report["reason"], report["target"]) == (
        "failed",
        "piece_mismatch",
        "default",
    )
    assert {k: report[k] for k in EMPTY} == EMPTY


def test_an_unreadable_pattern_has_a_null_pattern_hash(tmp_path: Path) -> None:
    out = tmp_path / "out" / "out.mosaic"
    with pytest.raises(BuildError) as e:
        build(tmp_path / "missing.yaml", "default", out)
    assert e.value.reason == "invalid_input"
    assert "missing.yaml" in str(e.value)
    report = load(out)
    assert report["pattern_hash"] is None
    assert {k: report[k] for k in EMPTY} == EMPTY


# --- Q1: weak ids -------------------------------------------------------------------------------


def test_a_key_from_the_piece_node_key_without_key_prop_is_weak(tmp_path: Path) -> None:
    _, report = run(tmp_path, [sensors("A", "B")], SENSOR)
    assert report["weak_ids"] == [{"type": "Sensor", "count": 2}]


def test_the_default_key_counts_as_from_the_piece_node_key(tmp_path: Path) -> None:
    types = {"Sensor": {"key": "tag", "from": {"list.Row": {"label": "label"}}}}
    _, report = run(tmp_path, [sensors("A")], types)
    assert report["weak_ids"] == [{"type": "Sensor", "count": 1}]


def test_a_piece_type_with_a_key_prop_is_not_weak(tmp_path: Path) -> None:
    _, report = run(tmp_path, [sensors("A", **NATURAL)], SENSOR)
    assert report["weak_ids"] == []


def test_a_key_from_another_field_is_not_weak(tmp_path: Path) -> None:
    types = {"Sensor": {"key": "tag", "from": {"list.Row": {"tag": "code"}}}}
    _, report = run(tmp_path, [("list", [node("Row:1", "1", code="A")], {})], types)
    assert report["weak_ids"] == []


def test_weak_count_is_nodes_after_step_6_that_a_weak_piece_node_maps_to(tmp_path: Path) -> None:
    # B is weak-keyed in `a`; C goes in step 6 (inferred evidence only); D comes only from the
    # natural-keyed `b`. A comes from both, so one weak-keyed piece node maps to it.
    types = {"Sensor": {"key": "tag", "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}}}}
    a = (
        "a",
        [node("Row:A", "A"), node("Row:B", "B"), node("Row:C", "C")],
        {
            "evidence": [
                evidence("Row:A", "row=1"),
                evidence("Row:B", "row=2"),
                evidence("Row:C", "row=3", method="inferred", confidence=0.9),
            ]
        },
    )
    b = ("b", [node("Row:A", "A"), node("Row:D", "D")], NATURAL)
    _, report = run(tmp_path, [a, b], types)
    assert report["counts"]["nodes"] == {"Sensor": 3}
    assert report["weak_ids"] == [{"type": "Sensor", "count": 2}]


def test_a_type_out_of_scope_is_not_listed_and_weak_ids_sort_by_type(tmp_path: Path) -> None:
    types = {
        "Zone": {"key": "z", "from": {"list.Z": {"z": "key"}}},
        "Valve": {"key": "v", "from": {"list.V": {"v": "key"}}},
        "Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
    }
    rows = [node("Row:A", "A"), node("V:1", "1"), node("Z:1", "1")]
    _, every = run(tmp_path / "all", [("list", rows, {})], types)
    assert [w["type"] for w in every["weak_ids"]] == ["Sensor", "Valve", "Zone"]
    narrow = {"ops": {"types": ["Zone", "Sensor"]}}
    _, some = run(tmp_path / "some", [("list", rows, {})], types, mosaics=narrow, target="ops")
    assert [w["type"] for w in some["weak_ids"]] == ["Sensor", "Zone"]


def test_a_node_merged_by_a_proposal_keeps_its_weak_key(tmp_path: Path) -> None:
    types = {"Sensor": {"key": "tag", "from": {"a.Row": {"tag": "key"}, "b.Row": {"tag": "key"}}}}
    pieces = [("a", [node("Row:A", "A")], NATURAL), ("b", [node("Row:B", "B")], {})]
    entries = [identity("p1", "Sensor:A", ["Sensor:B"])]
    _, report = run(tmp_path, pieces, types, entries=entries)
    assert report["counts"]["nodes"] == {"Sensor": 1}
    assert report["weak_ids"] == [{"type": "Sensor", "count": 1}]


# --- Q3: sorting of proposals ----------------------------------------------------------------


def test_proposals_outdated_first_then_no_longer_applies_in_file_order(tmp_path: Path) -> None:
    edges = {"feeds": {"from": "Sensor", "to": "Sensor", "mentions": "feeds.*"}}
    entries = [
        edge_proposal("e1", "feeds", "Sensor:A", "Sensor:Z"),
        identity("i1", "Sensor:Z", ["x"]),
        edge_proposal("e2", "feeds", "Sensor:Z", "Sensor:A"),
    ]
    _, report = run(tmp_path, [sensors("A")], SENSOR, edges, entries=entries)
    assert report["proposals"] == [
        {"id": "e1", "status": "no_longer_applies"},
        {"id": "i1", "status": "no_longer_applies"},
        {"id": "e2", "status": "no_longer_applies"},
    ]


def test_outdated_proposals_come_before_those_that_no_longer_apply(tmp_path: Path) -> None:
    first = tmp_path / "first"
    built, _ = run(first, [sensors("A")], SENSOR)
    assert isinstance(built, Built)
    second = tmp_path / "second"
    second.mkdir()
    path = second / "list.tessera"
    h = tessera(path, [node("Row:A", "A")])
    entries = [identity("i1", "Sensor:Z", ["x"]), identity("i2", "Sensor:A", ["y"])]
    out = second / "out" / "out.mosaic"
    build(
        pattern(second, [f"list@{h}"], SENSOR),
        "default",
        out,
        pieces=[path],
        proposals=proposals(second, entries, built_from="f" * 64),
        previous=built.path,
    )
    assert load(out)["proposals"] == [
        {"id": "i1", "status": "outdated"},
        {"id": "i2", "status": "outdated"},
        {"id": "i1", "status": "no_longer_applies"},
    ]


# --- Q3 and Q4: notices ---------------------------------------------------------------------


def test_notices_one_per_piece_and_text_every_piece_sorted(tmp_path: Path) -> None:
    # `zeta` is out of the target's scope and is listed anyway; `plain` has no notice.
    types = {
        "Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
        "Zone": {"key": "z", "from": {"zeta.Z": {"z": "key"}}},
        "Valve": {"key": "v", "from": {"plain.V": {"v": "key"}}},
    }
    pieces = [
        ("zeta", [node("Z:1", "1")], {"notice": "Ü licence"}),
        ("list", [node("Row:A", "A")], {"notice": "CC-BY 4.0"}),
        ("plain", [node("V:1", "1")], {}),
    ]
    _, report = run(tmp_path, pieces, types, mosaics={"ops": {"types": ["Sensor"]}}, target="ops")
    assert report["notices"] == [
        {"piece": "list", "text": "CC-BY 4.0"},
        {"piece": "zeta", "text": "Ü licence"},
    ]


def test_a_mosaic_piece_lists_each_distinct_notice_once(tmp_path: Path) -> None:
    path = tmp_path / "two.mosaic"
    content = Content(
        header=Header(kind="mosaic", producer="test/1", pattern_hash="0" * 64, target="t"),
        sources=[
            Source(id="p/c.csv", kind="file", hash="c" * 64, notice="B notice"),
            Source(id="p/b.csv", kind="file", hash="b" * 64, notice="A notice"),
            Source(id="p/a.csv", kind="file", hash="a" * 64, notice="B notice"),
            Source(id="p/d.csv", kind="file", hash="d" * 64),
        ],
        types=[Type(name="Row", kind="node", key_prop="k")],
        nodes=[node("Row:A", "A")],
        evidence=[evidence("Row:A", "row=1", source="p/a.csv")],
    )
    h = mosaic(path, content)
    out = tmp_path / "out" / "out.mosaic"
    build(
        pattern(tmp_path, [f"two@{h}"], {"Thing": {"key": "k", "from": {"two.Row": {"k": "key"}}}}),
        "default",
        out,
        pieces=[path],
    )
    assert load(out)["notices"] == [
        {"piece": "two", "text": "A notice"},
        {"piece": "two", "text": "B notice"},
    ]


# --- Q5: mention scope ----------------------------------------------------------------------


def test_mentions_of_a_rule_the_target_does_not_declare_are_not_reported(tmp_path: Path) -> None:
    # The target keeps only Step, so `reads` (Step → Sensor) is not declared.
    pieces = [sensors("T-1"), procedure(("T-9", "verify.arg0"))]
    built, report = run(tmp_path, pieces, DOCS, READS, mosaics=strict(types=["Step"]), target="ops")
    assert isinstance(built, Built)
    assert (report["mentions"], report["stale_references"]) == ([], [])


def test_mentions_whose_containing_node_step_6_drops_are_not_reported(tmp_path: Path) -> None:
    step = procedure(("T-9", "verify.arg0"))
    step[2]["evidence"] = [
        evidence("Step:S1", "row=1", method="inferred", confidence=0.9, source="proc.txt")
    ]
    built, report = run(
        tmp_path, [sensors("T-1"), step], DOCS, READS, mosaics=strict(), target="ops"
    )
    assert isinstance(built, Built)
    assert report["counts"]["nodes"] == {"Sensor": 1, "Step": 0}
    assert (report["mentions"], report["stale_references"]) == ([], [])


def test_mentions_and_stale_references_sort_by_piece_and_locator(tmp_path: Path) -> None:
    step = procedure(("x", "verify.a"), ("y", "verify.a"), ("z", "verify.a"))
    step[2]["mentions"] = list(reversed(step[2]["mentions"]))
    _, report = run(tmp_path, [sensors("T-1"), step], DOCS, READS)
    assert [m["locator"] for m in report["mentions"]] == ["line=1", "line=2", "line=3"]
    assert [s["locator"] for s in report["stale_references"]] == ["line=1", "line=2", "line=3"]


TIES = {
    **DOCS,
    "Zone": {"key": "z", "from": {"list.Z": {"z": "key"}}},
    "Valve": {"key": "v", "from": {"list.V": {"v": "key"}}},
}


def tied(tmp_path: Path, edges: dict[str, Any]) -> dict[str, Any]:
    """One mention ``t`` at ``line=1``, resolved by each rule of ``edges``.

    ``t`` names no Zone, the Valves 1 and 2, and the Sensors T-1 and T-2 (aliases).
    """
    rows = [node(i, i.split(":")[1]) for i in ("Row:T-1", "Row:T-2", "Z:1", "V:1", "V:2")]
    aliases = [Alias("t", n, "source") for n in ("Row:T-1", "Row:T-2", "V:1", "V:2")]
    _, report = run(
        tmp_path, [("list", rows, {"aliases": aliases}), procedure(("t", "verify.x"))], TIES, edges
    )
    return report


def test_ties_sort_stale_references_by_type(tmp_path: Path) -> None:
    # §7.3 (review of #93): stale references by piece, locator, `type` and name. One mention
    # gives one entry per rule, so ties differ in the rule's `to` type.
    edges = {
        "zones": {"from": "Step", "to": "Zone", "mentions": "verify.*"},
        "steps": {"from": "Step", "to": "Step", "mentions": "verify.*"},
    }
    report = tied(tmp_path, edges)
    assert [(s["type"], s["name"]) for s in report["stale_references"]] == [
        ("Step", "t"),
        ("Zone", "t"),
    ]


def test_ties_sort_mentions_by_status_then_candidates(tmp_path: Path) -> None:
    # §7.3 (review of #93): mentions by piece, locator, role, text, status, then candidates.
    edges = {
        "zones": {"from": "Step", "to": "Zone", "mentions": "verify.*"},
        "valves": {"from": "Step", "to": "Valve", "mentions": "verify.*"},
        "reads": {"from": "Step", "to": "Sensor", "mentions": "verify.*"},
    }
    report = tied(tmp_path, edges)
    assert [(m["status"], m["candidates"]) for m in report["mentions"]] == [
        ("ambiguous", ["Sensor:T-1", "Sensor:T-2"]),
        ("ambiguous", ["Valve:1", "Valve:2"]),
        ("unmatched", []),
    ]


# --- Q6: counts ---------------------------------------------------------------------------------


def test_counts_list_every_type_in_scope_and_declared_edge_type(tmp_path: Path) -> None:
    types = {
        "Sensor": {"key": "tag", "from": {"list.Row": {"tag": "key"}}},
        "Zone": {"key": "z", "from": {"list.Z": {"z": "key"}}},
        "Valve": {"key": "v", "from": {"list.V": {"v": "key"}}},
    }
    edges = {
        "in_zone": {"from": "Sensor", "to": "Zone", "mentions": "zone.*"},
        "feeds": {"from": "Valve", "to": "Sensor", "mentions": "feeds.*"},
    }
    # Zone:1 has only inferred evidence, so step 6 drops it and Zone has no rows.
    rows = [node("Row:A", "A"), node("Row:B", "B"), node("V:1", "1"), node("Z:1", "1")]
    rows_evidence = [
        evidence("Row:A", "row=1"),
        evidence("Row:B", "row=2"),
        evidence("V:1", "row=3"),
        evidence("Z:1", "row=4", method="inferred", confidence=0.9),
    ]
    piece = ("list", rows, {"evidence": rows_evidence})
    narrow = {"ops": {"types": ["Zone", "Sensor"]}}
    _, report = run(tmp_path, [piece], types, edges, mosaics=narrow, target="ops")
    assert report["counts"] == {"nodes": {"Sensor": 2, "Zone": 0}, "edges": {"in_zone": 0}}
    assert list(report["counts"]["nodes"]) == ["Sensor", "Zone"]


# --- the byte format (builder convention on #17) ----------------------------------------------


def _key_order(value: Any, schema: dict[str, Any]) -> None:
    """Every object's keys come in the order of its schema's ``properties``."""
    if "$ref" in schema:
        schema = SCHEMA["$defs"][schema["$ref"].rsplit("/", 1)[1]]
    if isinstance(value, dict) and "properties" in schema:
        order = list(schema["properties"])
        assert list(value) == [k for k in order if k in value], (list(value), order)
        for k, v in value.items():
            _key_order(v, schema["properties"][k])
    elif isinstance(value, list) and "items" in schema:
        for item in value:
            _key_order(item, schema["items"])


def test_keys_come_in_schema_order(tmp_path: Path) -> None:
    pieces = [
        ("a", [node("Row:A", "A", unit="F")], {"aliases": [Alias("temp", "Row:A", "source")]}),
        ("b", [node("Row:A", "A", unit="C")], {"aliases": [Alias("TEMP", "Row:A", "source")]}),
    ]
    _, report = run(tmp_path, pieces, RENAMED)
    assert report["conflicts"] and report["alias_conflicts"] and report["weak_ids"]
    assert list(report) == SCHEMA["required"]
    _key_order(report, SCHEMA)


def test_utf_8_two_space_indent_non_ascii_kept_lf_and_a_final_newline(tmp_path: Path) -> None:
    _conflicting(tmp_path)
    raw = (tmp_path / "out" / REPORT).read_bytes()
    text = raw.decode("utf-8")
    assert "°F" in text and "\\u" not in text
    assert "\r" not in text
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text == json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n"
    assert '\n  "format": "0.1",\n' in text
