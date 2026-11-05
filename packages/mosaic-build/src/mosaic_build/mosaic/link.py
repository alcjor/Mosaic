"""Steps 4 and 5 of a build: identity proposals and link (Specification 0.1, section 7.1).

**Step 4** (:func:`apply_identities`, sections 5.5 and 7.1 step 4). Accepted identity
proposals are applied in the order of the proposals file:

- Each name in ``same_as``, in its listed order, becomes an alias of ``node`` with
  ``origin = proposal``; ``proposals.yaml`` is its piece for alias conflicts.
- A name that is the id of a node merges that node into ``node``: its own aliases follow right
  after, in alias order (``text`` under ``NOCASE``, section 3.6); its property values, evidence
  and external references move to ``node``; and its piece nodes map to ``node`` from then on.
  The earliest piece still wins each property across the merged nodes.
- An id that an earlier proposal merged away stands for the node it was merged into, following
  each merge in turn; a proposal that would merge a node into itself merges nothing.
- An accepted proposal whose ``node`` is no node of the build no longer applies and has no
  effect. A ``same_as`` id that names no node only becomes an alias.
- When the previous mosaic of the target is given and ``built_from`` is not a prefix of its
  knowledge hash, every proposal in the file is outdated, whatever its decision. This affects
  only the build report.

**Step 5** (:func:`link`, sections 5.3 and 7.1 step 5). Edges are made in this build order:

- ``map`` entries copy piece edges whose two ends map to nodes of the declared types, with
  their qualifier, props and evidence (``prop`` kept; ``sid`` and ``via`` as in step 3). Pieces
  are taken in ``pieces`` order, then edge types in pattern order, their ``map`` entries in
  listed order, and the piece's edges in ``eid`` order. Other piece edges are not copied and not
  reported.
- Mention rules make an edge for every mention whose role matches (a ``*`` segment matches
  exactly one segment) from the canonical node of its containing node, of the rule's ``from``
  type, to the one node of the ``to`` type whose key equals the mention text after the ``to``
  type's ``normalise`` steps (by UTF-8 bytes) or one of whose aliases after step 4 equals it
  under ``NOCASE``. No match is an unmatched mention and a stale reference; several are an
  ambiguous mention. A mention whose containing node maps to no ``from`` node is skipped.
- Accepted edge proposals add an **extracted** edge sourced to ``proposals.yaml`` at
  ``entry=<id>``, produced by ``decided_by``. Their ends resolve through the merges of step 4; an
  end that is no node of the build means the proposal no longer applies.

Edges equal in ``(src, type, dst, qualifier)`` are one edge with all their evidence; their
props merge key by key, the earliest piece winning each key, a differing value a conflict.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from typing import Any

from mosaic_format.canonical_json import canonical_json
from mosaic_format.writer import EdgeKey, Evidence, ExternalRef, Source

from mosaic_build.mosaic.errors import BuildError
from mosaic_build.mosaic.merge import (
    PIECE_KINDS,
    Assembly,
    Given,
    Linked,
    MentionReport,
    Merged,
    ProposalStatus,
    StaleReference,
    _nid,
    _via,
    evidence_key,
    nocase,
)
from mosaic_build.mosaic.normalise import DEFAULT_STEPS, normalise
from mosaic_build.mosaic.pieces import Inputs, Piece

PROPOSALS = "proposals.yaml"
"""The ``source`` id of the proposals file, and its piece name in alias conflicts (3.2, 7.1)."""


def resolve(a: Assembly, node_id: str) -> str:
    """The node ``node_id`` stands for: following each merge of step 4 in turn."""
    while node_id in a.merged_into:
        node_id = a.merged_into[node_id]
    return node_id


def _accepted(inputs: Inputs, kind: str) -> Iterator[Mapping[str, Any]]:
    data = inputs.proposals
    for p in () if data is None else data["proposals"]:
        if p["kind"] == kind and p["decision"] == "accepted":
            yield p


def _proposals_source(inputs: Inputs, a: Assembly) -> None:
    """Add ``proposals.yaml`` (kind ``file``) to ``source`` once a proposal is applied (3.2)."""
    if inputs.proposals_path is None or inputs.proposals_hash is None:
        raise ValueError("an applied proposal needs the proposals file")
    if any(s.id == PROPOSALS for s in a.sources):
        return
    a.sources.append(
        Source(
            id=PROPOSALS,
            kind="file",
            hash=inputs.proposals_hash,
            path=inputs.proposals_path.name,
        )
    )


def _alias_order(given: Given) -> bytes:
    """Alias order (section 3.6): ``text`` under ``NOCASE``."""
    return nocase(str(given.value)).encode("utf-8")


def _absorb(a: Assembly, node: Merged, other: Merged) -> None:
    """Merge ``other`` into ``node`` (step 4): aliases, values, evidence, references, pieces."""
    node.aliases.extend(sorted(other.aliases, key=_alias_order))
    for prop, values in other.values.items():
        node.values.setdefault(prop, []).extend(values)

    evidence: list[Evidence] = []
    seen: set[tuple[object, ...]] = set()
    for row in a.evidence:
        if row.subject == other.id:
            row = replace(row, subject=node.id)
        key = evidence_key(row)
        if key not in seen:
            seen.add(key)
            evidence.append(row)
    a.evidence = evidence

    refs: list[ExternalRef] = []
    seen_refs: set[tuple[str, str, str, str]] = set()
    for ref in a.external_refs:
        if ref.node == other.id:
            ref = replace(ref, node=node.id)
        identity = (ref.node, ref.system, ref.kind, canonical_json(ref.locator))
        if identity not in seen_refs:
            seen_refs.add(identity)
            refs.append(ref)
    a.external_refs = refs

    for piece_node, targets in a.canonical.items():
        if other.id in targets:
            moved = [node.id if t == other.id else t for t in targets]
            a.canonical[piece_node] = tuple(dict.fromkeys(moved))
    a.merged_into[other.id] = node.id


def apply_identities(inputs: Inputs, a: Assembly) -> None:
    """Step 4: flag outdated proposals and apply accepted identity proposals to ``a``."""
    data = inputs.proposals
    if data is None:
        return
    previous = inputs.previous_hash
    if previous is not None and not previous.startswith(data["built_from"]):
        a.proposals.extend(ProposalStatus(p["id"], "outdated") for p in data["proposals"])

    rank = len(inputs.pieces)
    for p in _accepted(inputs, "identity"):
        node = a.nodes.get(resolve(a, p["node"]))
        if node is None:
            a.proposals.append(ProposalStatus(p["id"], "no_longer_applies"))
            continue
        _proposals_source(inputs, a)
        for name in p["same_as"]:
            node.aliases.append(Given(name, PROPOSALS, rank, "proposal"))
            other = resolve(a, name)
            if other != node.id and other in a.nodes:
                _absorb(a, node, a.nodes.pop(other))


# --- step 5 ----------------------------------------------------------------------------------


class _Linker:
    """Adds edges and evidence to an assembly: one edge per ``(src, type, dst, qualifier)``."""

    def __init__(self, a: Assembly) -> None:
        self.a = a
        self.seen = {evidence_key(e) for e in a.evidence}

    def edge(self, key: EdgeKey) -> Linked:
        found = self.a.edges.get(key)
        if found is None:
            found = self.a.edges[key] = Linked(key)
        return found

    def evidence(self, row: Evidence) -> None:
        key = evidence_key(row)
        if key not in self.seen:
            self.seen.add(key)
            self.a.evidence.append(row)


def _ends(a: Assembly, piece: Piece, old_id: str, type_: str) -> list[str]:
    """The canonical nodes of ``type_`` that piece node ``old_id`` maps to, in build order."""
    return [n for n in a.canonical.get((piece.name, old_id), ()) if a.nodes[n].type == type_]


def _edge_props(where: str, text: object) -> dict[str, Any]:
    """A piece edge's ``props``, which must be an I-JSON object (sections 3.1 and 3.8)."""
    if text is None:
        return {}
    try:
        canonical_json(str(text))
        props = json.loads(str(text))
    except ValueError as e:
        raise BuildError("invalid_input", f"{where}: props are not I-JSON (3.1): {e}") from None
    if not isinstance(props, dict):
        raise BuildError("invalid_input", f"{where}: props are not a JSON object")
    return props


def _edge_evidence(piece: Piece) -> dict[int, list[tuple[Any, ...]]]:
    """A piece's edge evidence by ``eid``, in ``evid`` order."""
    found: dict[int, list[tuple[Any, ...]]] = {}
    for row in piece.file.query(
        "SELECT e.eid, e.prop, s.id, e.locator, e.method, e.producer, e.confidence, e.via,"
        " sn.text FROM evidence AS e JOIN source AS s USING (sid)"
        " LEFT JOIN snippet AS sn USING (evid) WHERE e.eid IS NOT NULL ORDER BY e.evid"
    ):
        found.setdefault(_nid(row[0]), []).append(row[1:])
    return found


def _map_edges(inputs: Inputs, a: Assembly, linker: _Linker) -> None:
    edges: Mapping[str, Any] = inputs.pattern.get("edges", {})
    for piece in inputs.pieces:
        evidence: dict[int, list[tuple[Any, ...]]] | None = None
        for type_name, definition in edges.items():
            for reference in definition.get("map", ()):
                name, _, piece_type = reference.rpartition(".")
                if name != piece.name:
                    continue
                if evidence is None:
                    evidence = _edge_evidence(piece)
                for eid, src, dst, qualifier, props_text in piece.file.query(
                    "SELECT e.eid, s.id, d.id, e.qualifier, e.props FROM edge AS e"
                    " JOIN node AS s ON s.nid = e.src JOIN node AS d ON d.nid = e.dst"
                    " WHERE e.type = ? ORDER BY e.eid",
                    (piece_type,),
                ):
                    where = f"piece {piece.name!r}, edge {piece_type!r} from {src!r} to {dst!r}"
                    props = _edge_props(where, props_text)
                    for s in _ends(a, piece, str(src), definition["from"]):
                        for d in _ends(a, piece, str(dst), definition["to"]):
                            key = EdgeKey(s, type_name, d, str(qualifier))
                            edge = linker.edge(key)
                            for prop, value in props.items():
                                edge.give(prop, value, piece)
                            for row in evidence.get(_nid(eid), []):
                                prop, source, locator, method, producer, confidence, via, sn = row
                                linker.evidence(
                                    Evidence(
                                        subject=key,
                                        source=f"{piece.name}/{source}",
                                        locator=str(locator),
                                        method=str(method),
                                        producer=str(producer),
                                        prop=None if prop is None else str(prop),
                                        confidence=None
                                        if confidence is None
                                        else float(confidence),
                                        via=_via(piece, str(src), via, where),
                                        snippet=None if sn is None else str(sn),
                                    )
                                )


def role_matches(rule: str, role: str) -> bool:
    """Whether a mention's ``role`` matches a rule: a ``*`` segment matches exactly one segment."""
    wanted, given = rule.split("."), role.split(".")
    return len(wanted) == len(given) and all(
        w in ("*", g) for w, g in zip(wanted, given, strict=True)
    )


class _Targets:
    """The nodes of one type a mention can name: by key and by alias under ``NOCASE``."""

    def __init__(self, a: Assembly, type_: str, steps: Sequence[str]) -> None:
        self.steps = steps
        self.keys: dict[str, str] = {}
        self.aliases: dict[str, list[str]] = {}
        for node in a.nodes.values():
            if node.type != type_:
                continue
            self.keys[node.key] = node.id
            for alias in node.kept_aliases()[0]:
                listed = self.aliases.setdefault(nocase(str(alias.value)), [])
                if node.id not in listed:
                    listed.append(node.id)

    def match(self, text: str) -> list[str]:
        """The ids of the nodes ``text`` names, each once, by UTF-8 bytes."""
        found = set(self.aliases.get(nocase(text), ()))
        key = self.keys.get(normalise(text, self.steps))
        if key is not None:
            found.add(key)
        return sorted(found, key=lambda i: i.encode("utf-8"))


def _tessera_source(piece: Piece) -> tuple[str, str]:
    """A tessera's one original source as copied (``<piece>/<id>``), and its header producer."""
    sources = piece.file.query(
        "SELECT id FROM source WHERE kind NOT IN (?, ?) ORDER BY sid", PIECE_KINDS
    )
    if len(sources) != 1:
        raise BuildError(
            "invalid_input",
            f"piece {piece.name!r}: a tessera has exactly one original source (3.9), "
            f"found {len(sources)}",
        )
    ((producer,),) = piece.file.query("SELECT producer FROM header")
    return f"{piece.name}/{sources[0][0]}", str(producer)


def _mention_edges(inputs: Inputs, a: Assembly, linker: _Linker) -> None:
    edges: Mapping[str, Any] = inputs.pattern.get("edges", {})
    rules = [(t, d) for t, d in edges.items() if "mentions" in d]
    if not rules:
        return
    targets: dict[str, _Targets] = {}
    for _, definition in rules:
        to = definition["to"]
        if to not in targets:
            steps = inputs.pattern["types"][to].get("normalise", DEFAULT_STEPS)
            targets[to] = _Targets(a, to, steps)

    for piece in inputs.pieces:
        if piece.kind != "tessera":
            continue  # mentions are tessera only (section 3.2)
        rows = piece.file.query(
            "SELECT m.text, m.locator, n.id, m.role FROM mention AS m"
            " JOIN node AS n USING (nid) ORDER BY m.mid"
        )
        if not rows:
            continue
        source, producer = _tessera_source(piece)
        for type_name, definition in rules:
            for text, locator, old_id, role in rows:
                text, locator, role = str(text), str(locator), str(role)
                if not role_matches(definition["mentions"], role):
                    continue
                sources = _ends(a, piece, str(old_id), definition["from"])
                if not sources:
                    continue
                found = targets[definition["to"]].match(text)
                if len(found) != 1:
                    status = "unmatched" if not found else "ambiguous"
                    a.mentions.append(
                        MentionReport(
                            status, role, text, piece.name, locator, tuple(found), type_name
                        )
                    )
                    if not found:
                        a.stale_references.append(
                            StaleReference(text, definition["to"], piece.name, locator)
                        )
                    continue
                for s in sources:
                    key = EdgeKey(s, type_name, found[0])
                    linker.edge(key)
                    linker.evidence(
                        Evidence(
                            subject=key,
                            source=source,
                            locator=locator,
                            method="extracted",
                            producer=producer,
                        )
                    )


def _proposed_edges(inputs: Inputs, a: Assembly, linker: _Linker) -> None:
    for p in _accepted(inputs, "edge"):
        src, dst = resolve(a, p["from"]), resolve(a, p["to"])
        if src not in a.nodes or dst not in a.nodes:
            a.proposals.append(ProposalStatus(p["id"], "no_longer_applies"))
            continue
        _proposals_source(inputs, a)
        key = EdgeKey(src, p["type"], dst)
        linker.edge(key)
        linker.evidence(
            Evidence(
                subject=key,
                source=PROPOSALS,
                locator=f"entry={p['id']}",
                method="extracted",
                producer=str(p["decided_by"]),
            )
        )


def _by_piece_and_locator(piece: str, locator: str) -> tuple[bytes, bytes]:
    return piece.encode("utf-8"), locator.encode("utf-8")


def link(inputs: Inputs, a: Assembly) -> None:
    """Step 5: make edges from ``map`` entries, then mention rules, then edge proposals."""
    linker = _Linker(a)
    _map_edges(inputs, a, linker)
    _mention_edges(inputs, a, linker)
    _proposed_edges(inputs, a, linker)
    a.mentions.sort(key=lambda m: _by_piece_and_locator(m.piece, m.locator))
    a.stale_references.sort(key=lambda s: _by_piece_and_locator(s.piece, s.locator))
