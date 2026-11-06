"""Step 7 of a build: derive (Specification 0.1, section 7.1 step 7, decision Q1 on #16).

The mosaic declares in ``type`` every node type in scope and every edge type whose ``from``
and ``to`` are both in scope, whether or not it has rows:

- ``description`` is the pattern's ``describe``, or NULL when there is none; a node type's
  ``key_prop`` is its ``key``; an edge type's ``from_type`` and ``to_type`` are its ends.
- A node type's ``props`` list every canonical property its field maps fill, except the key
  property, ``label`` and ``summary``. Each takes the kind the piece type declares for the field
  it is mapped from, the earliest piece in ``pieces`` that declares one winning (``from``
  entries of one piece in pattern order); a property no piece declares is ``json``. A field
  held in a piece node's column (``key``, ``label``, ``summary``) is not among its type's
  declared ``props``, so it declares no kind.
- A ``map`` edge type's ``props`` list every property its ``map`` piece edge types declare,
  each with the kind of the earliest piece in ``pieces`` (``map`` entries of one piece in listed
  order), since ``map`` copies edge properties as they are; a property the mosaic's edges of
  that type hold that no piece declares is ``json``. An edge type made by mentions or proposals
  declares ``{}``.

Link counts and the full-text index are derived by the sealed writer; vectors (section 6), when
the target has them on, by :func:`mosaic_build.mosaic.vectors.node_vectors` in the build.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from mosaic_format.writer import Type

from mosaic_build.mosaic.errors import BuildError
from mosaic_build.mosaic.map import COLUMNS, TEXT_COLUMNS, entries
from mosaic_build.mosaic.merge import Assembly
from mosaic_build.mosaic.pieces import Inputs, Piece
from mosaic_build.mosaic.target import Target

KINDS = ("text", "integer", "number", "boolean", "json")
"""The value kinds of a declared property (section 3.4)."""

FALLBACK = "json"
"""The kind of a property no piece declares."""


def _declared(piece: Piece, name: str, kind: str) -> Mapping[str, str]:
    """The declared properties of a piece's type ``name`` (section 3.4); the piece is untrusted."""
    rows = piece.file.query("SELECT props FROM type WHERE name = ? AND kind = ?", (name, kind))
    if not rows:
        return {}
    where = f"piece {piece.name!r}, type {name!r}"
    try:
        props = json.loads(str(rows[0][0]))
    except ValueError as e:
        raise BuildError("invalid_input", f"{where}: props are not JSON (3.4): {e}") from None
    if not isinstance(props, dict) or not all(v in KINDS for v in props.values()):
        raise BuildError(
            "invalid_input",
            f"{where}: props must map each property to one of {', '.join(KINDS)} (3.4)",
        )
    return props


def _earliest(candidates: Iterable[tuple[int, int, str, str | None]]) -> dict[str, str]:
    """Property → kind: of (piece rank, entry order, property, kind or None), the first kind."""
    kinds: dict[str, str] = {}
    for _, _, prop, kind in sorted(candidates, key=lambda c: (c[0], c[1])):
        if kind is not None and prop not in kinds:
            kinds[prop] = kind
    return kinds


def _node_type(inputs: Inputs, name: str, definition: Mapping[str, Any]) -> Type:
    listed: dict[str, None] = {}
    candidates: list[tuple[int, int, str, str | None]] = []
    for order, entry in enumerate(e for e in entries(inputs.pattern) if e.type == name):
        piece = inputs.piece(entry.piece)
        declared = _declared(piece, entry.piece_type, "node")
        for prop, field in entry.fields.items():
            if prop == entry.key_prop or prop in TEXT_COLUMNS:
                continue
            listed.setdefault(prop)
            kind = None if field in COLUMNS else declared.get(field)
            candidates.append((piece.rank, order, prop, kind))
    kinds = _earliest(candidates)
    return Type(
        name=name,
        kind="node",
        description=definition.get("describe"),
        key_prop=definition["key"],
        props=json.dumps({p: kinds.get(p, FALLBACK) for p in listed}),
    )


def _edge_type(inputs: Inputs, a: Assembly, name: str, definition: Mapping[str, Any]) -> Type:
    props: dict[str, str] = {}
    if "map" in definition:
        listed: dict[str, None] = {}
        candidates: list[tuple[int, int, str, str | None]] = []
        for order, reference in enumerate(definition["map"]):
            piece_name, _, piece_type = reference.rpartition(".")
            piece = inputs.piece(piece_name)
            for prop, kind in _declared(piece, piece_type, "edge").items():
                listed.setdefault(prop)
                candidates.append((piece.rank, order, prop, kind))
        for key, edge in a.edges.items():
            if key.type == name:
                for prop in edge.values:
                    listed.setdefault(prop)
        kinds = _earliest(candidates)
        props = {p: kinds.get(p, FALLBACK) for p in listed}
    return Type(
        name=name,
        kind="edge",
        description=definition.get("describe"),
        from_type=definition["from"],
        to_type=definition["to"],
        props=json.dumps(props),
    )


def declare(inputs: Inputs, a: Assembly, t: Target) -> list[Type]:
    """Step 7: the types the mosaic of target ``t`` declares, from the selected ``a``."""
    pattern = inputs.pattern
    in_scope = t.node_types(pattern)
    found = [_node_type(inputs, name, pattern["types"][name]) for name in in_scope]
    for name, definition in pattern.get("edges", {}).items():
        if definition["from"] in in_scope and definition["to"] in in_scope:
            found.append(_edge_type(inputs, a, name, definition))
    return found
