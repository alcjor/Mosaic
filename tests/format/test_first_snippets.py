"""``first_snippets``: each node's first snippet in ``evid`` order (Spec 0.1, 3.6 and 6).

Section 6's node text ends in "the snippet"; the maintainer chose the first of the node's own
snippets in ``evid`` order (answer on #105). ``evid`` is the canonical rank of section 3.6, so
the first snippet must not depend on the order evidence is given in.
"""

from dataclasses import replace

from mosaic_format.writer import (
    Content,
    Edge,
    EdgeKey,
    Evidence,
    Header,
    Node,
    Source,
    Type,
    first_snippets,
)

P = "test/1"


def _content(evidence: list[Evidence]) -> Content:
    return Content(
        header=Header(kind="mosaic", producer=P, pattern_hash="0" * 64, target="t"),
        sources=[
            Source(id="a", kind="file", hash="1" * 64),
            Source(id="b", kind="file", hash="2" * 64),
        ],
        types=[Type(name="Item", kind="node"), Type(name="in", kind="edge")],
        nodes=[Node(id="Item:x", type="Item", key="x"), Node(id="Item:y", type="Item", key="y")],
        edges=[],
        evidence=evidence,
    )


def test_the_first_snippet_follows_the_canonical_evidence_order() -> None:
    rows = [
        Evidence("Item:x", "b", "row=1", "extracted", P, snippet="from b"),
        Evidence("Item:x", "a", "row=9", "extracted", P, snippet="from a, row 9"),
        Evidence("Item:x", "a", "row=10", "extracted", P, snippet="from a, row 10"),
    ]
    # sid ranks a before b; within a, locators compare by UTF-8 bytes: "row=10" < "row=9".
    assert first_snippets(_content(rows)) == {"Item:x": "from a, row 10"}
    assert first_snippets(_content(rows[::-1])) == {"Item:x": "from a, row 10"}


def test_rows_without_a_snippet_are_skipped_and_nodes_without_any_are_absent() -> None:
    rows = [
        Evidence("Item:x", "a", "row=1", "extracted", P),
        Evidence("Item:x", "a", "row=2", "extracted", P, snippet="second"),
        Evidence("Item:y", "a", "row=3", "extracted", P),
    ]
    assert first_snippets(_content(rows)) == {"Item:x": "second"}


def test_an_empty_snippet_is_a_snippet() -> None:
    rows = [
        Evidence("Item:x", "a", "row=1", "extracted", P, snippet=""),
        Evidence("Item:x", "a", "row=2", "extracted", P, snippet="later"),
    ]
    assert first_snippets(_content(rows)) == {"Item:x": ""}


def test_edge_evidence_does_not_count() -> None:
    c = _content([Evidence("Item:y", "a", "row=5", "extracted", P, snippet="own")])
    edge = EdgeKey("Item:x", "in", "Item:y")
    c = replace(
        c,
        edges=[Edge(type="in", src="Item:x", dst="Item:y")],
        evidence=[*c.evidence, Evidence(edge, "a", "row=1", "extracted", P, snippet="edge")],
    )
    assert first_snippets(c) == {"Item:y": "own"}
