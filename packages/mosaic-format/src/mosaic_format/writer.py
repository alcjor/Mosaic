"""Write content sealed (Specification 0.1, section 3.6 and section 7.1 step 8).

A builder hands over content with text ids only, in any order: sources, types, nodes, edges,
aliases, evidence (each with its snippet, if any), mentions, external references, source texts
and vectors. It never assigns ``sid``, ``nid``, ``eid``, ``evid``, ``mid`` or ``xid``: the
writer ranks the content by the canonical order of section 3.6, with text ordered by its UTF-8
bytes, and numbers the rows densely from 1.

Sealing then writes the derived tables, computes both hashes, writes the header and runs
``ANALYZE`` and ``VACUUM``:

- ``link_count`` (mosaic only): the number of edges per node, edge type and direction;
- ``search`` (both profiles): one row per node, ``rowid = nid``, holding the node's label, its
  aliases in alias order, its summary, and the snippets of its own evidence in ``evid`` order.
  Aliases and snippets are joined with a newline, which no token contains.

The writer refuses, with an error naming the row, content it cannot rank or resolve: a
reference to a node, edge, source or type that is not given; two rows with one identity; two
evidence rows equal in every ranked column (below), which no order can tell apart; mentions in
a mosaic and vectors in a tessera (section 3.2); vectors that are not one per node; text that
contains U+0000 (section 3.1, decision on issue #39); JSON text that is not I-JSON (below).

Every JSON text (``settings``, type, node and edge ``props``, ``via``, an external reference's
``locator``) is written in the canonical form of RFC 8785 (section 3.1, decision on issue #59), so
equal JSON spelled differently gives the same file and hash; see ``mosaic_format.canonical_json``.

Evidence of one subject with the same source and locator is ranked by the rest of the row,
``(prop, method, producer, confidence, via)``, with NULL before any value and ``confidence``
compared by its hashed value ``CAST(round(confidence*1000000) AS INTEGER)`` (decision on
issue #41). Builders merge exact duplicates before writing.

Every other rule is left to the schema's constraints and the checker. A failed write leaves no
file behind, and an existing file is never overwritten.
"""

import os
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import NamedTuple

from mosaic_format import FORMAT_VERSION
from mosaic_format.canonical_json import canonical_json
from mosaic_format.file import SIDECARS, create
from mosaic_format.hashes import knowledge_hash, quote_confidence, vector_hash

PLACEHOLDER_HASH = "0" * 64
"""Written into the header until the knowledge hash, which does not cover it, is known."""

SEARCH_SEPARATOR = "\n"
"""Joins several aliases or snippets in one ``search`` column."""


@dataclass(frozen=True)
class Header:
    """The header fields a builder chooses (section 3.3); the writer adds version and hashes."""

    kind: str
    producer: str
    settings: str = "{}"
    pattern_hash: str | None = None
    target: str | None = None
    ai_model: str | None = None
    embed_model: str | None = None


@dataclass(frozen=True)
class Source:
    """A source or piece, by its text ``id``; ``text`` is its entire text (``source_text``)."""

    id: str
    kind: str
    hash: str
    path: str | None = None
    notice: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class Type:
    """A declared node or edge type (section 3.4)."""

    name: str
    kind: str
    description: str | None = None
    key_prop: str | None = None
    from_type: str | None = None
    to_type: str | None = None
    props: str = "{}"


@dataclass(frozen=True)
class Node:
    """A node, by its text ``id``; ``props`` is JSON text or None."""

    id: str
    type: str
    key: str
    label: str | None = None
    summary: str | None = None
    props: str | None = None


class EdgeKey(NamedTuple):
    """What identifies an edge (section 3.4): source node id, type, target node id, qualifier."""

    src: str
    type: str
    dst: str
    qualifier: str = ""


@dataclass(frozen=True)
class Edge:
    """An edge between two node ids."""

    type: str
    src: str
    dst: str
    qualifier: str = ""
    props: str | None = None

    @property
    def key(self) -> EdgeKey:
        return EdgeKey(self.src, self.type, self.dst, self.qualifier)


@dataclass(frozen=True)
class Alias:
    """Another name of a node."""

    text: str
    node: str
    origin: str


@dataclass(frozen=True)
class Evidence:
    """One evidence row: its subject is a node id or an :class:`EdgeKey` (section 3.5)."""

    subject: str | EdgeKey
    source: str
    locator: str
    method: str
    producer: str
    prop: str | None = None
    confidence: float | None = None
    via: str | None = None
    snippet: str | None = None


@dataclass(frozen=True)
class Mention:
    """A name the source uses without defining it (section 4.2); tessera only."""

    text: str
    locator: str
    node: str
    role: str
    kind: str


@dataclass(frozen=True)
class ExternalRef:
    """A key into data that stays outside (section 3.10); ``locator`` is JSON text."""

    node: str
    system: str
    kind: str
    locator: str
    source: str


@dataclass(frozen=True)
class Vector:
    """The 48-byte sign vector of one node (section 3.7); mosaic only."""

    node: str
    bits: bytes


@dataclass(frozen=True)
class Content:
    """Everything a sealed file holds apart from its derived tables, in any order."""

    header: Header
    sources: Sequence[Source] = ()
    types: Sequence[Type] = ()
    nodes: Sequence[Node] = ()
    edges: Sequence[Edge] = ()
    aliases: Sequence[Alias] = ()
    evidence: Sequence[Evidence] = ()
    mentions: Sequence[Mention] = ()
    external_refs: Sequence[ExternalRef] = ()
    vectors: Sequence[Vector] = ()


@dataclass(frozen=True)
class Sealed:
    """A sealed file and the hashes in its header."""

    path: Path
    knowledge_hash: str
    vector_hash: str | None = None


type _InputRow = (
    Header | Source | Type | Node | Edge | Alias | Evidence | Mention | ExternalRef | Vector
)


def _row_name(row: _InputRow) -> str:
    """How an error names an input row, as the writer's other refusals do."""
    match row:
        case Header():
            return "header"
        case Source(id=id_):
            return f"source {id_!r}"
        case Type(name=name):
            return f"type {name!r}"
        case Node(id=id_):
            return f"node {id_!r}"
        case Edge():
            return _edge_name(row.key)
        case Alias(text=text, node=node):
            return f"alias {text!r} of node {node!r}"
        case Evidence(locator=locator):
            return f"evidence at {locator!r}"
        case Mention(locator=locator):
            return f"mention at {locator!r}"
        case ExternalRef(locator=locator, node=node):
            return f"external_ref {locator!r} of node {node!r}"
        case Vector(node=node):
            return f"vector of node {node!r}"


def _refuse_nul(content: Content) -> None:
    """Section 3.1 (decision on #39): no text value contains U+0000.

    SQLite reads text as ending at the first U+0000 (``quote()``, ``length()``), so such text
    would be hashed and read truncated. The writer must not change content, so it refuses.
    """
    c = content
    rows: list[_InputRow] = [c.header, *c.sources, *c.types, *c.nodes, *c.edges, *c.aliases]
    rows += [*c.evidence, *c.mentions, *c.external_refs, *c.vectors]
    for row in rows:
        for field in fields(row):
            value = getattr(row, field.name)
            parts = value if isinstance(value, EdgeKey) else (value,)
            if any(isinstance(part, str) and "\x00" in part for part in parts):
                raise ValueError(
                    f"{_row_name(row)}: {field.name} contains U+0000, which text never holds (3.1)"
                )


_JSON_FIELDS: dict[type, tuple[str, ...]] = {
    Header: ("settings",),
    Type: ("props",),
    Node: ("props",),
    Edge: ("props",),
    Evidence: ("via",),
    ExternalRef: ("locator",),
}
"""The JSON text fields of each input row (section 3.1)."""


def _canonical_row[R: _InputRow](row: R) -> R:
    changes: dict[str, str] = {}
    for name in _JSON_FIELDS.get(type(row), ()):
        value = getattr(row, name)
        if value is None:
            continue
        try:
            changes[name] = canonical_json(value)
        except ValueError as e:
            raise ValueError(f"{_row_name(row)}: {name}: {e} (3.1)") from None
    return replace(row, **changes) if changes else row


def _canonical_json(content: Content) -> Content:
    """Section 3.1 (decision on #59): every JSON text in RFC 8785 canonical form."""
    c = content
    return replace(
        c,
        header=_canonical_row(c.header),
        types=[_canonical_row(t) for t in c.types],
        nodes=[_canonical_row(n) for n in c.nodes],
        edges=[_canonical_row(e) for e in c.edges],
        evidence=[_canonical_row(ev) for ev in c.evidence],
        external_refs=[_canonical_row(x) for x in c.external_refs],
    )


def _utf8(text: str, where: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as e:
        raise ValueError(f"{where}: text is not valid Unicode ({e.reason})") from None


_ASCII_LOWER = bytes.maketrans(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ", b"abcdefghijklmnopqrstuvwxyz")


def _nocase(raw: bytes) -> bytes:
    """Sort key of SQLite's ``NOCASE`` collation: UTF-8 bytes with ASCII letters folded."""
    return raw.translate(_ASCII_LOWER)


def _nullable[T](
    value: T | None, rank: Callable[[T, str], object], where: str
) -> tuple[()] | tuple[object]:
    """Sort key of a nullable column: NULL before any value, as SQLite orders them."""
    return () if value is None else (rank(value, where),)


def _confidence_rank(value: object, where: str) -> int:
    """``confidence`` ranks by the value it hashes as, so two rows that hash alike tie."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = float(value)  # stored with REAL affinity
    try:
        return int(quote_confidence(value, where=f"{where}: confidence"))
    except (ValueError, OverflowError) as e:
        raise ValueError(f"{where}: confidence {value!r} cannot be ranked ({e})") from None


def _unique[T, K: Hashable](items: Iterable[T], key: Callable[[T], K], what: str) -> dict[K, T]:
    found: dict[K, T] = {}
    for item in items:
        k = key(item)
        if k in found:
            raise ValueError(f"{what} {k!r} is given twice")
        found[k] = item
    return found


def _edge_name(key: EdgeKey) -> str:
    return f"edge ({key.src!r}, {key.type!r}, {key.dst!r}, qualifier {key.qualifier!r})"


class _Ranked(NamedTuple):
    sources: list[Source]
    sid: dict[str, int]
    types: list[Type]
    nodes: list[Node]
    nid: dict[str, int]
    edges: list[tuple[int, int, Edge]]
    eid: dict[EdgeKey, int]
    evidence: list[tuple[int | None, int | None, int, Evidence]]
    mentions: list[tuple[int, Mention]]
    external_refs: list[tuple[int, int, ExternalRef]]
    vectors: list[tuple[int, bytes]]
    aliases: list[tuple[int, Alias]]


def _rank(content: Content) -> _Ranked:
    """Resolve text ids and order every table canonically (section 3.6)."""
    kind = content.header.kind
    sources = _unique(content.sources, lambda s: s.id, "source")
    ordered_sources = sorted(sources.values(), key=lambda s: _utf8(s.id, f"source {s.id!r}"))
    sid = {s.id: n for n, s in enumerate(ordered_sources, start=1)}

    types = _unique(content.types, lambda t: t.name, "type")
    ordered_types = sorted(types.values(), key=lambda t: _utf8(t.name, f"type {t.name!r}"))

    nodes = _unique(content.nodes, lambda n: n.id, "node")
    ordered_nodes = sorted(nodes.values(), key=lambda n: _utf8(n.id, f"node {n.id!r}"))
    nid = {n.id: i for i, n in enumerate(ordered_nodes, start=1)}

    def node_of(node: str, where: str) -> int:
        if node not in nid:
            raise ValueError(f"{where}: node {node!r} is not given")
        return nid[node]

    def source_of(source: str, where: str) -> int:
        if source not in sid:
            raise ValueError(f"{where}: source {source!r} is not given")
        return sid[source]

    for n in ordered_nodes:
        if n.type not in types:
            raise ValueError(f"node {n.id!r}: type {n.type!r} is not given")

    edges = _unique(content.edges, lambda e: e.key, "edge")
    resolved_edges = []
    for key, e in edges.items():
        where = _edge_name(key)
        if e.type not in types:
            raise ValueError(f"{where}: type {e.type!r} is not given")
        src, dst = node_of(e.src, where), node_of(e.dst, where)
        resolved_edges.append(((src, _utf8(e.type, where), dst, _utf8(e.qualifier, where)), e))
    resolved_edges.sort(key=lambda r: r[0])
    ordered_edges = [(k[0], k[2], e) for k, e in resolved_edges]
    eid = {e.key: i for i, (_, _, e) in enumerate(ordered_edges, start=1)}

    ranked_evidence = []
    seen: set[tuple[object, ...]] = set()
    for ev in content.evidence:
        if isinstance(ev.subject, EdgeKey):
            name = _edge_name(ev.subject)
            if ev.subject not in eid:
                raise ValueError(f"evidence at {ev.locator!r}: {name} is not given")
            subject = (1, eid[ev.subject])
        else:
            name = f"node {ev.subject!r}"
            subject = (0, node_of(ev.subject, f"evidence at {ev.locator!r}"))
        where = f"evidence of {name} at {ev.locator!r}"
        order = (
            *subject,
            source_of(ev.source, where),
            _utf8(ev.locator, where),
            _nullable(ev.prop, _utf8, where),
            _utf8(ev.method, where),
            _utf8(ev.producer, where),
            _nullable(ev.confidence, _confidence_rank, where),
            _nullable(ev.via, _utf8, where),
        )
        if order in seen:
            raise ValueError(
                f"{where}: two evidence rows of {name} from source {ev.source!r} at locator "
                f"{ev.locator!r} are equal in prop, method, producer, confidence and via; "
                "merge them before writing"
            )
        seen.add(order)
        ranked_evidence.append((order, ev))
    ranked_evidence.sort(key=lambda r: r[0])
    ordered_evidence = [
        (None if o[0] else o[1], o[1] if o[0] else None, o[2], ev) for o, ev in ranked_evidence
    ]

    if content.mentions and kind != "tessera":
        raise ValueError(f"mention: a {kind} holds no mentions; they are tessera only (3.2)")
    ranked_mentions = []
    for m in content.mentions:
        where = f"mention at {m.locator!r}"
        ranked_mentions.append(((node_of(m.node, where), _utf8(m.locator, where)), m))
    ranked_mentions.sort(key=lambda r: r[0])

    ranked_refs = []
    for x in content.external_refs:
        where = f"external_ref {x.system!r} {x.kind!r} {x.locator!r} of node {x.node!r}"
        order = (
            node_of(x.node, where),
            _utf8(x.system, where),
            _utf8(x.kind, where),
            _utf8(x.locator, where),
        )
        ranked_refs.append((order, source_of(x.source, where), x))
    ranked_refs.sort(key=lambda r: r[0])

    vectors = _unique(content.vectors, lambda v: v.node, "vector of node")
    if vectors and kind != "mosaic":
        raise ValueError(f"vector: a {kind} holds no vectors; they are mosaic only (3.2)")
    if vectors:
        missing = [n.id for n in ordered_nodes if n.id not in vectors]
        if missing:
            raise ValueError(f"vector: none given for node {missing[0]!r}; one per node (3.7)")
        if content.header.embed_model is None:
            raise ValueError("header: vectors are given but embed_model is not (3.7)")
    elif content.header.embed_model is not None:
        raise ValueError("header: embed_model is given but no vectors are (3.7)")
    ordered_vectors = sorted(
        (node_of(v.node, f"vector of node {v.node!r}"), v.bits) for v in vectors.values()
    )

    ranked_aliases = []
    for a in content.aliases:
        where = f"alias {a.text!r} of node {a.node!r}"
        ranked_aliases.append(((_nocase(_utf8(a.text, where)), node_of(a.node, where)), a))
    ranked_aliases.sort(key=lambda r: r[0])

    return _Ranked(
        sources=ordered_sources,
        sid=sid,
        types=ordered_types,
        nodes=ordered_nodes,
        nid=nid,
        edges=ordered_edges,
        eid=eid,
        evidence=ordered_evidence,
        mentions=[(o[0], m) for o, m in ranked_mentions],
        external_refs=[(o[0], s, x) for o, s, x in ranked_refs],
        vectors=ordered_vectors,
        aliases=[(o[1], a) for o, a in ranked_aliases],
    )


def _insert(con: sqlite3.Connection, table: str, row: tuple[object, ...], where: str) -> None:
    marks = ", ".join("?" * len(row))
    try:
        con.execute(f"INSERT INTO {table} VALUES ({marks})", row)
    except sqlite3.IntegrityError as e:
        raise ValueError(f"{where}: refused by the schema ({e})") from None


def _write_rows(con: sqlite3.Connection, header: Header, r: _Ranked) -> None:
    h = header
    # vector_hash and embed_model are set with the hashes, as the header requires them together.
    row = (1, FORMAT_VERSION, h.kind, h.producer, h.settings, PLACEHOLDER_HASH, None, None)
    _insert(con, "header", (*row, h.pattern_hash, h.target, h.ai_model), "header")
    for sid, s in enumerate(r.sources, start=1):
        _insert(con, "source", (sid, s.id, s.kind, s.path, s.hash, s.notice), f"source {s.id!r}")
    for t in r.types:
        row = (t.name, t.kind, t.description, t.key_prop, t.from_type, t.to_type, t.props)
        _insert(con, "type", row, f"type {t.name!r}")
    for nid, n in enumerate(r.nodes, start=1):
        row = (nid, n.id, n.type, n.key, n.label, n.summary, n.props)
        _insert(con, "node", row, f"node {n.id!r}")
    for eid, (src, dst, e) in enumerate(r.edges, start=1):
        row = (eid, e.type, src, dst, e.qualifier, e.props)
        _insert(con, "edge", row, _edge_name(e.key))
    for nid, a in r.aliases:
        _insert(con, "alias", (a.text, nid, a.origin), f"alias {a.text!r} of node {a.node!r}")
    for evid, (nid, eid, sid, ev) in enumerate(r.evidence, start=1):
        where = f"evidence at {ev.locator!r}"
        row = (evid, nid, eid, ev.prop, sid, ev.locator, ev.method, ev.producer)
        _insert(con, "evidence", (*row, ev.confidence, ev.via), where)
    for evid, (_, _, _, ev) in enumerate(r.evidence, start=1):
        if ev.snippet is not None:
            _insert(con, "snippet", (evid, ev.snippet), f"snippet of evidence at {ev.locator!r}")
    for mid, (nid, m) in enumerate(r.mentions, start=1):
        row = (mid, m.text, m.locator, nid, m.role, m.kind)
        _insert(con, "mention", row, f"mention at {m.locator!r}")
    for sid, s in enumerate(r.sources, start=1):
        if s.text is not None:
            _insert(con, "source_text", (sid, s.text), f"source_text of {s.id!r}")
    for xid, (nid, sid, x) in enumerate(r.external_refs, start=1):
        row = (xid, nid, x.system, x.kind, x.locator, sid)
        _insert(con, "external_ref", row, f"external_ref {x.locator!r} of node {x.node!r}")
    for nid, bits in r.vectors:
        _insert(con, "vector", (nid, bits), f"vector of node {r.nodes[nid - 1].id!r}")


def _write_derived(con: sqlite3.Connection, kind: str, r: _Ranked) -> None:
    if kind == "mosaic":
        counts: Counter[tuple[int, bytes, str]] = Counter()
        names: dict[bytes, str] = {}
        for src, dst, e in r.edges:
            name = e.type.encode("utf-8")
            names[name] = e.type
            counts[(src, name, "out")] += 1
            counts[(dst, name, "in")] += 1
        for nid, name, direction in sorted(counts):
            row = (nid, names[name], direction, counts[(nid, name, direction)])
            con.execute("INSERT INTO link_count VALUES (?, ?, ?, ?)", row)

    aliases: defaultdict[int, list[str]] = defaultdict(list)
    for nid, a in r.aliases:
        aliases[nid].append(a.text)
    snippets: defaultdict[int, list[str]] = defaultdict(list)
    for nid, _, _, ev in r.evidence:
        if nid is not None and ev.snippet is not None:
            snippets[nid].append(ev.snippet)
    for nid, n in enumerate(r.nodes, start=1):
        row = (
            nid,
            n.label,
            SEARCH_SEPARATOR.join(aliases[nid]) or None,
            n.summary,
            SEARCH_SEPARATOR.join(snippets[nid]) or None,
        )
        con.execute(
            "INSERT INTO search (rowid, label, aliases, summary, snippets) VALUES (?, ?, ?, ?, ?)",
            row,
        )


def _remove(target: Path) -> None:
    for leftover in [target, *(target.with_name(target.name + s) for s in SIDECARS)]:
        leftover.unlink(missing_ok=True)


def first_snippets(content: Content) -> dict[str, str]:
    """Each node's first snippet: of its own evidence rows that keep one, the first in ``evid``
    order (sections 3.6 and 6). Nodes without a snippet are absent; edge evidence does not count.

    The order is the one :func:`seal` writes, so the snippet is the one a reader finds first.
    """
    ranked = _rank(_canonical_json(content))
    first: dict[str, str] = {}
    for nid, _, _, ev in ranked.evidence:
        if nid is not None and ev.snippet is not None and isinstance(ev.subject, str):
            first.setdefault(ev.subject, ev.snippet)
    return first


def seal(path: str | os.PathLike[str], content: Content) -> Sealed:
    """Write ``content`` as a new sealed file at ``path`` and return its hashes.

    Rows are ranked and written in canonical order (section 3.6), the derived tables are
    filled, both hashes are computed and written into the header with ``format_version``,
    and ``ANALYZE`` and ``VACUUM`` run (section 7.1 step 8). The same content in any order
    gives the same knowledge hash and, with the same SQLite, the same bytes.
    """
    _refuse_nul(content)  # refuse bad content before any file exists
    content = _canonical_json(content)
    header = content.header  # after canonicalizing: settings is written as canonical JSON
    ranked = _rank(content)
    target = create(path, header.kind)
    try:
        con = sqlite3.connect(target, isolation_level=None)
        try:
            con.execute("PRAGMA foreign_keys = ON")
            con.execute("BEGIN")
            con.execute("PRAGMA defer_foreign_keys = ON")
            _write_rows(con, header, ranked)
            _write_derived(con, header.kind, ranked)
            knowledge = knowledge_hash(con)
            vectors = vector_hash(con)
            try:
                con.execute(
                    "UPDATE header SET knowledge_hash = ?, vector_hash = ?, embed_model = ?",
                    (knowledge, vectors, header.embed_model),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(f"header: refused by the schema ({e})") from None
            try:
                con.execute("COMMIT")
            except sqlite3.IntegrityError as e:
                raise ValueError(f"{target}: refused by the schema at commit ({e})") from None
            con.execute("ANALYZE")
            con.execute("VACUUM")
        finally:
            con.close()
    except BaseException:
        _remove(target)
        raise
    return Sealed(target, knowledge, vectors)
