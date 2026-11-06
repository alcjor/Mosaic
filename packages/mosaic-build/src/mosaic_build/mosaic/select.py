"""Step 6 of a build: select for the target (Specification 0.1, section 7.1 step 6 and 5.4).

In this order (decisions Q2 and Q3 on #16):

1. **Types.** Keep nodes of the types in scope, and edges whose two ends are kept.
2. **Trust.** Drop inferred evidence rows below the trust policy: ``reviewed`` drops every
   inferred row, ``all`` none, and a number the rows below it (rows at or above it stay).
3. **Values follow their evidence.** A value in ``props``, ``label`` or ``summary`` (of a node,
   or in an edge's ``props``) is removed when the piece that gave it had evidence rows whose
   ``prop`` is that property on that subject and trust dropped all of them. Rows without
   ``prop`` are no evidence on a property, so a value with only node-level rows, or none, stays.
   The winner and the conflicts of steps 3 to 5 are then decided among the values that remain.
4. **Anything left without evidence** goes: a node with no evidence left, with its aliases and
   external references, and an edge with none left or with an end that went.
5. **Evidence.** Under ``primary``, one row per fact: a fact is one subject and one ``prop``, a
   row without ``prop`` being a fact of its own. The row of the highest-priority piece is kept:
   piece order, where a row's piece is the one whose copied source it names (so a mention edge's
   row has the priority of the piece holding the mention) and ``proposals.yaml`` comes after
   every piece; among that piece's rows, the first in canonical order (section 3.6). Under
   ``all``, every row stays.
6. **Text.** ``none`` drops every snippet and source text; ``snippets`` drops source texts;
   ``full`` keeps both. Sources themselves stay whole, cited or not (section 3.2).
7. **Mentions** for the report: only those of rules whose edge type the target declares (both
   ends in scope, section 7.1 step 7), and not those whose containing node went. Stale
   references follow them (section 7.2, decision Q5 on #17).
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mosaic_format.canonical_json import canonical_json
from mosaic_format.hashes import quote_confidence
from mosaic_format.writer import EdgeKey, Evidence

from mosaic_build.mosaic.link import PROPOSALS
from mosaic_build.mosaic.merge import Assembly, Given
from mosaic_build.mosaic.pieces import Inputs
from mosaic_build.mosaic.target import Target

type Subject = str | EdgeKey


def piece_of(source: str) -> str:
    """The piece an evidence row came from: the prefix of its copied source (section 3.2).

    ``proposals.yaml`` is its own: an accepted edge proposal's row names it.
    """
    return source if source == PROPOSALS else source.split("/", 1)[0]


def trusted(row: Evidence, trust: str | int | float) -> bool:
    """Whether a row enters under the trust policy (section 5.4)."""
    if row.method != "inferred" or trust == "all":
        return True
    if trust == "reviewed":
        return False
    return row.confidence is not None and row.confidence >= float(trust)


def _values_follow_evidence(
    values: dict[str, list[Given]],
    subject: Subject,
    had: set[tuple[Subject, str, str]],
    left: set[tuple[Subject, str, str]],
) -> None:
    """Remove each value whose piece had rows on its property and has none left (Q3)."""
    for prop in list(values):
        kept = [
            g
            for g in values[prop]
            if (subject, g.piece, prop) not in had or (subject, g.piece, prop) in left
        ]
        if kept:
            values[prop] = kept
        else:
            del values[prop]


def _on_property(rows: list[Evidence]) -> set[tuple[Subject, str, str]]:
    return {(e.subject, piece_of(e.source), e.prop) for e in rows if e.prop is not None}


type _Order = tuple[int, bytes, bytes, bytes, bytes, tuple[int, ...], tuple[bytes, ...]]


def _canonical_order(row: Evidence, ranks: Mapping[str, int]) -> _Order:
    """A row's priority within its fact: piece order, then canonical order (section 3.6).

    Within one fact, subject and ``prop`` are equal; the rest of section 3.6's order is
    ``(sid, locator, method, producer, confidence, via)``, with ``sid`` ranked by the source
    id's UTF-8 bytes, NULL before any value and ``confidence`` as it is hashed.
    """
    confidence: tuple[int, ...] = (
        () if row.confidence is None else (int(quote_confidence(row.confidence)),)
    )
    via: tuple[bytes, ...] = () if row.via is None else (canonical_json(row.via).encode("utf-8"),)
    return (
        ranks[piece_of(row.source)],
        row.source.encode("utf-8"),
        row.locator.encode("utf-8"),
        row.method.encode("utf-8"),
        row.producer.encode("utf-8"),
        confidence,
        via,
    )


def _primary(rows: list[Evidence], ranks: Mapping[str, int]) -> list[Evidence]:
    """One row per fact (subject and ``prop``), in the order the rows came."""
    best: dict[tuple[Subject, str | None], Evidence] = {}
    for row in rows:
        fact = (row.subject, row.prop)
        held = best.get(fact)
        if held is None or _canonical_order(row, ranks) < _canonical_order(held, ranks):
            best[fact] = row
    chosen = {id(r) for r in best.values()}
    return [r for r in rows if id(r) in chosen]


def select(inputs: Inputs, a: Assembly, t: Target) -> None:
    """Step 6: select ``a`` for target ``t``, in place."""
    in_scope = set(t.node_types(inputs.pattern))
    a.nodes = {i: n for i, n in a.nodes.items() if n.type in in_scope}
    a.edges = {k: e for k, e in a.edges.items() if k.src in a.nodes and k.dst in a.nodes}
    rows = [e for e in a.evidence if _kept(e.subject, a)]

    kept = [e for e in rows if trusted(e, t.trust)]
    had, left = _on_property(rows), _on_property(kept)
    for node_id, node in a.nodes.items():
        _values_follow_evidence(node.values, node_id, had, left)
    for key, edge in a.edges.items():
        _values_follow_evidence(edge.values, key, had, left)

    cited = {e.subject for e in kept}
    a.nodes = {i: n for i, n in a.nodes.items() if i in cited}
    a.edges = {
        k: e for k, e in a.edges.items() if k in cited and k.src in a.nodes and k.dst in a.nodes
    }
    kept = [e for e in kept if _kept(e.subject, a)]
    a.external_refs = [x for x in a.external_refs if x.node in a.nodes]

    if t.evidence == "primary":
        ranks = {p.name: p.rank for p in inputs.pieces}
        ranks[PROPOSALS] = len(inputs.pieces)
        kept = _primary(kept, ranks)
    if t.text == "none":
        kept = [replace(e, snippet=None) if e.snippet is not None else e for e in kept]
    a.evidence = kept
    if t.text != "full":
        a.sources = [replace(s, text=None) if s.text is not None else s for s in a.sources]

    edges: Mapping[str, Any] = inputs.pattern.get("edges", {})
    declared = {n for n, d in edges.items() if d["from"] in in_scope and d["to"] in in_scope}
    a.mentions = [m for m in a.mentions if _bears(m.edge_type, m.nodes, declared, a)]
    a.stale_references = [
        s for s in a.stale_references if _bears(s.edge_type, s.nodes, declared, a)
    ]


def _bears(edge_type: str, nodes: tuple[str, ...], declared: set[str], a: Assembly) -> bool:
    """Whether a mention bears on the mosaic: its rule is declared and its node is kept."""
    return edge_type in declared and any(n in a.nodes for n in nodes)


def _kept(subject: Subject, a: Assembly) -> bool:
    return subject in a.edges if isinstance(subject, EdgeKey) else subject in a.nodes
