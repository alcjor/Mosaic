"""Step 3 of a build: merge mapped nodes (Specification 0.1, section 7.1 step 3).

Nodes of the same type and key are one node. Every value a property is given is kept with
the piece that gave it, in build order, so the winner can be found again after step 4 merges
nodes:

- **Properties** (``label``, ``summary`` and every key of ``props``): the value from the
  earliest piece in ``pieces`` wins, and within one piece the first in build order. A value
  that differs from the winner (compared in canonical JSON form) is a conflict. Label and
  summary conflicts are recorded too; the build report shows them only for a strict target
  (section 7.3).
- **Aliases** are a union, in build order: per piece, its own aliases in its alias order
  (``text`` under ``NOCASE``, then ``nid``), then the aliases step 2 makes from it in step 2's
  order (the key as written, then a mosaic piece's old id). Aliases of one node equal under
  ``NOCASE`` are one: the first added keeps its spelling and ``origin``; a later one spelled
  differently is an alias conflict, one that differs only in ``origin`` is not.
- **External references** are a union; references equal in node, system, kind and locator
  are one row, which keeps the ``sid`` of the first in build order (section 3.10).
- **Evidence**: every row of a fact the mosaic holds is kept. A row whose ``prop`` names a
  mapped field gets each canonical property that field fills; a row whose ``prop`` names a
  field the pattern does not map is dropped; rows about the whole node are kept (decision 6
  on #14). Exact duplicates are merged (section 3.5). Edge evidence comes with the edges, in
  step 5.
- **Sources**: one row per piece, and a copy of each piece's original sources with its id
  prefixed ``<piece>/`` (section 3.2). Evidence and external references name the copy; evidence
  from a mosaic piece gets that piece's knowledge hash appended to its ``via`` (section 3.5).
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from mosaic_format.canonical_json import canonical_json
from mosaic_format.hashes import quote_confidence
from mosaic_format.writer import Alias, Edge, EdgeKey, Evidence, ExternalRef, Node, Source

from mosaic_build.mosaic.errors import BuildError
from mosaic_build.mosaic.map import Mapped, map_nodes
from mosaic_build.mosaic.pieces import Inputs, Piece

PIECE_KINDS = ("tessera", "mosaic")
"""Source kinds that name a piece, never an original source (section 3.2)."""


@dataclass(frozen=True)
class Given:
    """A value of one property, or an alias, as one piece gave it."""

    value: Any
    piece: str
    rank: int
    """The piece's position in ``pieces``: lower wins."""
    origin: str | None = None
    """An alias's ``origin``; None for a property value."""


@dataclass(frozen=True)
class Conflict:
    """A property given differing values (section 7.2): the winner and the losers in build order."""

    node: str
    property: str
    winner: Given
    losers: tuple[Given, ...]


@dataclass(frozen=True)
class EdgeConflict:
    """An edge property given differing values (sections 7.1 step 5 and 7.3)."""

    edge: EdgeKey
    property: str
    winner: Given
    losers: tuple[Given, ...]


@dataclass(frozen=True)
class MentionReport:
    """A mention a rule could not resolve (sections 5.3 and 7.2).

    ``status`` is ``unmatched`` or ``ambiguous``; ``candidates`` are the matching node ids when
    ambiguous, by UTF-8 bytes. ``edge_type`` names the rule; one entry per mention and rule.
    """

    status: str
    role: str
    text: str
    piece: str
    locator: str
    candidates: tuple[str, ...]
    edge_type: str


@dataclass(frozen=True)
class StaleReference:
    """A name that resolves to nothing (section 7.2): in 0.1, an unmatched mention, with the
    rule's ``to`` type."""

    name: str
    type: str
    piece: str
    locator: str


@dataclass(frozen=True)
class ProposalStatus:
    """A proposal the build report lists (section 5.5): ``outdated`` or ``no_longer_applies``."""

    id: str
    status: str


@dataclass(frozen=True)
class AliasConflict:
    """Aliases of one node equal under ``NOCASE`` but spelled differently (section 7.2)."""

    node: str
    winner: Given
    losers: tuple[Given, ...]


def nocase(text: str) -> str:
    """The text as SQLite's ``NOCASE`` collation compares it: ASCII letters folded."""
    return text.translate(_ASCII_LOWER)


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _same(a: Any, b: Any) -> bool:
    return a == b if isinstance(a, str) and isinstance(b, str) else _canonical(a) == _canonical(b)


def _canonical(value: Any) -> str:
    return canonical_json(json.dumps(value, ensure_ascii=False))


def _winner(values: list[Given]) -> Given:
    """The value from the earliest piece, the first in build order within one piece."""
    return min(values, key=lambda g: g.rank)


def _differing(values: dict[str, list[Given]]) -> list[tuple[str, Given, tuple[Given, ...]]]:
    """Each property given differing values: (property, winner, losers in build order).

    Properties are taken by UTF-8 bytes; a loser equal to another from the same piece is listed
    once.
    """
    found: list[tuple[str, Given, tuple[Given, ...]]] = []
    for prop in sorted(values, key=lambda p: p.encode("utf-8")):
        win = _winner(values[prop])
        losers: list[Given] = []
        for given in sorted(values[prop], key=lambda g: g.rank):
            if given is win or _same(given.value, win.value):
                continue
            if not any(_same(given.value, g.value) and given.piece == g.piece for g in losers):
                losers.append(given)
        if losers:
            found.append((prop, win, tuple(losers)))
    return found


def _props_text(props: dict[str, Any]) -> str | None:
    return json.dumps(props, ensure_ascii=False) if props else None


@dataclass
class Merged:
    """One canonical node and everything its pieces gave it, in build order."""

    id: str
    type: str
    key: str
    values: dict[str, list[Given]] = field(default_factory=dict)
    """Property (``label``, ``summary`` or a key of ``props``) → the values given."""
    aliases: list[Given] = field(default_factory=list)
    """Every alias given, before ``NOCASE`` duplicates are merged."""

    def give(self, prop: str, value: Any, piece: Piece) -> None:
        self.values.setdefault(prop, []).append(Given(value, piece.name, piece.rank))

    def winner(self, prop: str) -> Given:
        """The value from the earliest piece, the first in build order within one piece."""
        return _winner(self.values[prop])

    def conflicts(self) -> list[Conflict]:
        return [Conflict(self.id, p, w, losers) for p, w, losers in _differing(self.values)]

    def kept_aliases(self) -> tuple[list[Given], list[AliasConflict]]:
        """The aliases kept, first added wins under ``NOCASE``, and the alias conflicts."""
        kept: dict[str, Given] = {}
        lost: dict[str, list[Given]] = {}
        for alias in self.aliases:
            folded = nocase(alias.value)
            winner = kept.setdefault(folded, alias)
            if winner is alias or alias.value == winner.value:
                continue
            losers = lost.setdefault(folded, [])
            if not any(alias.value == g.value and alias.piece == g.piece for g in losers):
                losers.append(alias)
        conflicts = [
            AliasConflict(self.id, kept[folded], tuple(losers)) for folded, losers in lost.items()
        ]
        conflicts.sort(key=lambda c: c.winner.value.encode("utf-8"))
        return list(kept.values()), conflicts

    def node(self) -> Node:
        """The node as the writer takes it: winning label, summary and props."""
        props = {p: self.winner(p).value for p in self.values if p not in ("label", "summary")}
        label = self.winner("label").value if "label" in self.values else None
        summary = self.winner("summary").value if "summary" in self.values else None
        return Node(
            id=self.id,
            type=self.type,
            key=self.key,
            label=label,
            summary=summary,
            props=_props_text(props),
        )


@dataclass
class Linked:
    """One canonical edge (step 5) and the props its piece edges gave it, in build order."""

    key: EdgeKey
    values: dict[str, list[Given]] = field(default_factory=dict)
    """Key of ``props`` → the values given; merged key by key like node properties."""

    def give(self, prop: str, value: Any, piece: Piece) -> None:
        self.values.setdefault(prop, []).append(Given(value, piece.name, piece.rank))

    def conflicts(self) -> list[EdgeConflict]:
        return [EdgeConflict(self.key, p, w, losers) for p, w, losers in _differing(self.values)]

    def edge(self) -> Edge:
        props = {p: _winner(given).value for p, given in self.values.items()}
        k = self.key
        return Edge(
            type=k.type, src=k.src, dst=k.dst, qualifier=k.qualifier, props=_props_text(props)
        )


@dataclass
class Assembly:
    """The result of steps 1-3, handed on to linking (steps 4-5) and selection (6-8)."""

    nodes: dict[str, Merged]
    """Canonical node id → node, in order of first appearance in build order."""
    sources: list[Source]
    evidence: list[Evidence]
    external_refs: list[ExternalRef]
    canonical: dict[tuple[str, str], tuple[str, ...]]
    """(piece, piece node id) → the canonical node ids it maps to, in build order."""
    merged_into: dict[str, str] = field(default_factory=dict)
    """Node id an identity proposal merged away → the node it was merged into (step 4)."""
    edges: dict[EdgeKey, Linked] = field(default_factory=dict)
    """Canonical edges in build order (step 5); their evidence is in :attr:`evidence`."""
    mentions: list[MentionReport] = field(default_factory=list)
    """Unmatched and ambiguous mentions, by piece and locator (UTF-8 bytes)."""
    stale_references: list[StaleReference] = field(default_factory=list)
    """Names that resolve to nothing, by piece and locator (UTF-8 bytes)."""
    proposals: list[ProposalStatus] = field(default_factory=list)
    """Outdated proposals in file order, then those that no longer apply, in file order."""

    def conflicts(self) -> list[Conflict]:
        """Every property conflict, by node id and property (UTF-8 bytes)."""
        found = [c for m in self.nodes.values() for c in m.conflicts()]
        found.sort(key=lambda c: (c.node.encode("utf-8"), c.property.encode("utf-8")))
        return found

    def aliases(self) -> list[Alias]:
        return [
            Alias(text=a.value, node=m.id, origin=str(a.origin))
            for m in self.nodes.values()
            for a in m.kept_aliases()[0]
        ]

    def alias_conflicts(self) -> list[AliasConflict]:
        """Every alias conflict, by node id and winning spelling (UTF-8 bytes)."""
        found = [c for m in self.nodes.values() for c in m.kept_aliases()[1]]
        found.sort(key=lambda c: (c.node.encode("utf-8"), c.winner.value.encode("utf-8")))
        return found

    def node_rows(self) -> list[Node]:
        return [m.node() for m in self.nodes.values()]

    def edge_rows(self) -> list[Edge]:
        return [e.edge() for e in self.edges.values()]

    def edge_conflicts(self) -> list[EdgeConflict]:
        """Every edge property conflict, by from, type, to, qualifier and property (section 7.3)."""
        found = [c for e in self.edges.values() for c in e.conflicts()]
        found.sort(
            key=lambda c: tuple(
                x.encode("utf-8")
                for x in (c.edge.src, c.edge.type, c.edge.dst, c.edge.qualifier, c.property)
            )
        )
        return found


def _sources(pieces: Sequence[Piece]) -> list[Source]:
    """A row per piece, then each piece's original sources as ``<piece>/<id>`` (section 3.2)."""
    rows: list[Source] = []
    for piece in pieces:
        rows.append(
            Source(id=piece.name, kind=piece.kind, hash=piece.knowledge_hash, path=piece.path)
        )
    for piece in pieces:
        for id_, kind, path, hash_, notice, text in piece.file.query(
            "SELECT s.id, s.kind, s.path, s.hash, s.notice, t.text"
            " FROM source AS s LEFT JOIN source_text AS t USING (sid) ORDER BY s.sid"
        ):
            if kind in PIECE_KINDS:
                continue
            rows.append(
                Source(
                    id=f"{piece.name}/{id_}",
                    kind=str(kind),
                    hash=str(hash_),
                    path=None if path is None else str(path),
                    notice=None if notice is None else str(notice),
                    text=None if text is None else str(text),
                )
            )
    return rows


def _where(piece: Piece, old_id: str) -> str:
    return f"piece {piece.name!r}, node {old_id!r}"


def _via(piece: Piece, old_id: str, via: object, where: str | None = None) -> str | None:
    """``via`` of evidence taken from ``piece``: a mosaic piece appends its hash (section 3.5).

    The piece is untrusted (section 3.8), so a ``via`` that is not an I-JSON array of text, or
    any ``via`` in a tessera (evidence straight from a tessera has none), fails the build with
    ``invalid_input`` instead of a ``ValueError`` later. ``where`` names the subject in that
    message; by default, the piece node ``old_id``.
    """
    where = _where(piece, old_id) if where is None else where
    if piece.kind != "mosaic":
        if via is not None:
            raise BuildError(
                "invalid_input",
                f"{where}: evidence of a tessera has a via; only evidence that passed through a "
                f"mosaic has one (3.5)",
            )
        return None
    hashes: list[object] = []
    if via is not None:
        try:
            hashes = json.loads(canonical_json(str(via)))
        except ValueError as e:
            raise BuildError(
                "invalid_input", f"{where}: evidence via is not I-JSON (3.1): {e}"
            ) from None
        if not isinstance(hashes, list) or not all(isinstance(h, str) for h in hashes):
            raise BuildError(
                "invalid_input", f"{where}: evidence via is not an array of knowledge hashes (3.5)"
            )
    return json.dumps([*hashes, piece.knowledge_hash])


def _locator(piece: Piece, old_id: str, locator: object) -> str:
    """An external reference's ``locator`` in canonical form, or the build fails (section 3.1)."""
    try:
        return canonical_json(str(locator))
    except ValueError as e:
        raise BuildError(
            "invalid_input",
            f"{_where(piece, old_id)}: external reference locator is not I-JSON (3.1): {e}",
        ) from None


def _nid(value: object) -> int:
    """A row id read from a piece; ``INTEGER PRIMARY KEY`` makes it an integer."""
    if not isinstance(value, int):
        raise TypeError(f"row id {value!r} is not an integer")
    return value


class _PieceRows:
    """The aliases, evidence and external references of one piece, by piece node ``nid``."""

    def __init__(self, piece: Piece) -> None:
        f = piece.file
        self.aliases: list[tuple[str, int, str]] = [
            (str(t), _nid(n), str(o))
            for t, n, o in f.query("SELECT text, nid, origin FROM alias ORDER BY text, nid")
        ]
        self.evidence: dict[int, list[tuple[Any, ...]]] = {}
        for row in f.query(
            "SELECT e.nid, e.prop, s.id, e.locator, e.method, e.producer, e.confidence, e.via,"
            " sn.text FROM evidence AS e JOIN source AS s USING (sid)"
            " LEFT JOIN snippet AS sn USING (evid) WHERE e.nid IS NOT NULL ORDER BY e.evid"
        ):
            self.evidence.setdefault(_nid(row[0]), []).append(row[1:])
        self.refs: dict[int, list[tuple[Any, ...]]] = {}
        for row in f.query(
            "SELECT x.nid, x.system, x.kind, x.locator, s.id"
            " FROM external_ref AS x JOIN source AS s USING (sid) ORDER BY x.xid"
        ):
            self.refs.setdefault(_nid(row[0]), []).append(row[1:])


def evidence_key(e: Evidence) -> tuple[object, ...]:
    """What makes two evidence rows equal (section 3.5): ``confidence`` as it is hashed."""
    confidence = quote_confidence(e.confidence)
    return (e.subject, e.prop, e.source, e.locator, e.method, e.producer, confidence, e.via)


def merge(inputs: Inputs, mapped: Iterable[Mapped] | None = None) -> Assembly:
    """Step 3: merge the mapped nodes (step 2 when ``mapped`` is None) into one assembly."""
    by_piece: dict[str, list[Mapped]] = {p.name: [] for p in inputs.pieces}
    for m in map_nodes(inputs) if mapped is None else mapped:
        by_piece[m.piece.name].append(m)

    nodes: dict[str, Merged] = {}
    canonical: dict[tuple[str, str], list[str]] = {}
    evidence: list[Evidence] = []
    seen_evidence: set[tuple[object, ...]] = set()
    refs: list[ExternalRef] = []
    seen_refs: set[tuple[str, str, str, str]] = set()

    for piece in inputs.pieces:
        rows = _PieceRows(piece)
        targets: dict[int, list[str]] = {}
        for m in by_piece[piece.name]:
            node = nodes.get(m.id)
            if node is None:
                node = nodes[m.id] = Merged(id=m.id, type=m.type, key=m.key)
            ids = targets.setdefault(m.nid, [])
            if m.id not in ids:
                ids.append(m.id)
            listed = canonical.setdefault((piece.name, m.old_id), [])
            if m.id not in listed:
                listed.append(m.id)
            for column, value in (("label", m.label), ("summary", m.summary)):
                if value is not None:
                    node.give(column, value, piece)
            for prop, value in m.props.items():
                node.give(prop, value, piece)

            renames = m.entry.renames()
            for (
                prop,
                source,
                locator,
                method,
                producer,
                confidence,
                via,
                snippet,
            ) in rows.evidence.get(m.nid, []):
                props: tuple[str | None, ...] = (
                    (None,) if prop is None else renames.get(str(prop), ())
                )
                for canonical_prop in props:
                    row = Evidence(
                        subject=m.id,
                        source=f"{piece.name}/{source}",
                        locator=str(locator),
                        method=str(method),
                        producer=str(producer),
                        prop=canonical_prop,
                        confidence=None if confidence is None else float(confidence),
                        via=_via(piece, m.old_id, via),
                        snippet=None if snippet is None else str(snippet),
                    )
                    key = evidence_key(row)
                    if key not in seen_evidence:
                        seen_evidence.add(key)
                        evidence.append(row)

            for system, kind, locator, source in rows.refs.get(m.nid, []):
                ref = ExternalRef(
                    node=m.id,
                    system=str(system),
                    kind=str(kind),
                    locator=str(locator),
                    source=f"{piece.name}/{source}",
                )
                identity = (ref.node, ref.system, ref.kind, _locator(piece, m.old_id, locator))
                if identity not in seen_refs:
                    seen_refs.add(identity)
                    refs.append(ref)

        # Aliases: the piece's own, in its alias order, then those step 2 makes from it.
        for text, nid, origin in rows.aliases:
            for node_id in targets.get(nid, []):
                nodes[node_id].aliases.append(Given(text, piece.name, piece.rank, origin))
        for m in by_piece[piece.name]:
            node = nodes[m.id]
            if m.written != m.key:
                node.aliases.append(Given(m.written, piece.name, piece.rank, "source"))
            if piece.kind == "mosaic":
                node.aliases.append(Given(m.old_id, piece.name, piece.rank, "pattern"))

    return Assembly(
        nodes=nodes,
        sources=_sources(inputs.pieces),
        evidence=evidence,
        external_refs=refs,
        canonical={k: tuple(v) for k, v in canonical.items()},
    )
