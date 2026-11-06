"""Step 2 of a build: map piece nodes to canonical nodes (Specification 0.1, section 7.1 step 2).

For each ``types.<T>.from`` entry, every node of that piece type becomes a canonical node of
type ``T`` by the entry's field map (section 5.2, decisions 1-4 and 7 on #14):

- A field map value names a field of the piece node: one of ``key``, ``label``, ``summary``
  (its columns), or else a key of its ``props``. A field that is NULL, JSON ``null`` or not
  there gives no value.
- The entry for the type's key property gives the key; without one, the piece node's ``key``
  does. A number becomes text in its canonical JSON form (``2020`` → ``"2020"``); a missing,
  NULL or boolean key, a JSON array or object, or one that is empty after ``strip`` and
  normalisation fails the build with ``invalid_input``. The key is never a property.
- ``strip`` removes its prefix from the key, then the normalisation steps run in order. The
  key as written, before ``strip``, is kept as an alias (``origin = source``) when it differs
  from the normalised key.
- An entry whose canonical property is ``label`` or ``summary`` fills that column; without
  one, the node takes the piece node's ``label`` and ``summary``. These columns hold text, so
  a non-text value for them fails the build with ``invalid_input`` (no decision covers it).
- Every other entry fills a property in ``props``.
- A node of a mosaic piece is mapped the same way; its old id becomes an alias with
  ``origin = pattern`` (in step 3).
- A piece node is **weak-keyed** when its key comes from the piece node's ``key`` (an entry
  for the key property naming ``key``, or no entry) and its piece type's ``key_prop`` is NULL:
  the key came from position, not a natural key (section 7.2, decision Q1 on #17; ADR-002).

Entries are taken in pattern order and, within an entry, the piece's nodes in ``nid`` order;
across pieces, in ``pieces`` order. That is the build order of step 3.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mosaic_format.canonical_json import canonical_json

from mosaic_build.mosaic.errors import BuildError
from mosaic_build.mosaic.normalise import DEFAULT_STEPS, normalise
from mosaic_build.mosaic.pieces import Inputs, Piece

COLUMNS = ("key", "label", "summary")
"""Fields of a piece node held in its own columns rather than in ``props``."""

TEXT_COLUMNS = ("label", "summary")
"""Canonical properties that fill a node column instead of ``props`` (section 5.2)."""

STRIP = "strip"
"""The reserved field map option (section 5.2)."""


@dataclass(frozen=True)
class Entry:
    """One ``types.<T>.from`` entry: the canonical type and the piece type it maps."""

    type: str
    key_prop: str
    steps: tuple[str, ...]
    piece: str
    piece_type: str
    fields: Mapping[str, str]
    """Canonical property → piece field, without ``strip``."""
    strip: str | None

    @property
    def reference(self) -> str:
        return f"{self.piece}.{self.piece_type}"

    def renames(self) -> dict[str, tuple[str, ...]]:
        """Piece field → the canonical properties it fills, the key property and columns too.

        Evidence about a field is renamed to these properties (step 3, decision 6 on #14).
        """
        filled: dict[str, list[str]] = {}
        for prop, field in self.fields.items():
            filled.setdefault(field, []).append(prop)
        if self.key_prop not in self.fields:
            filled.setdefault("key", []).append(self.key_prop)
        for column in TEXT_COLUMNS:
            if column not in self.fields:
                filled.setdefault(column, []).append(column)
        return {field: tuple(props) for field, props in filled.items()}


@dataclass(frozen=True)
class Mapped:
    """One piece node mapped to a canonical node, in build order."""

    entry: Entry
    piece: Piece
    nid: int
    """The piece node's row id: joins its evidence, aliases and external references."""
    old_id: str
    """The piece node's id."""
    key: str
    written: str
    """The key as written in the source: the field's value as text, before ``strip``."""
    label: str | None
    summary: str | None
    props: Mapping[str, Any]
    weak: bool = False
    """Whether the key came from position rather than a natural key (section 7.2)."""

    @property
    def type(self) -> str:
        return self.entry.type

    @property
    def id(self) -> str:
        return f"{self.entry.type}:{self.key}"


def entries(pattern: Mapping[str, Any]) -> list[Entry]:
    """Every ``from`` entry of the pattern, in pattern order."""
    found: list[Entry] = []
    for type_name, definition in pattern["types"].items():
        steps = tuple(definition.get("normalise", DEFAULT_STEPS))
        for reference, field_map in definition["from"].items():
            piece, _, piece_type = reference.rpartition(".")
            fields = {p: f for p, f in field_map.items() if p != STRIP}
            found.append(
                Entry(
                    type=type_name,
                    key_prop=definition["key"],
                    steps=steps,
                    piece=piece,
                    piece_type=piece_type,
                    fields=fields,
                    strip=field_map.get(STRIP),
                )
            )
    return found


_ABSENT = object()


def _field(columns: Mapping[str, Any], props: Mapping[str, Any], name: str) -> Any:
    """A field of a piece node, or ``_ABSENT``; NULL and JSON ``null`` are absent too."""
    value = columns[name] if name in COLUMNS else props.get(name)
    return _ABSENT if value is None else value


def _where(entry: Entry, old_id: str) -> str:
    return f"piece {entry.piece!r}, node {old_id!r} ({entry.reference} → {entry.type})"


def _key_text(entry: Entry, old_id: str, field: str, value: Any) -> str:
    """The key's value as text (decision 3 on #14), or the build fails."""
    if value is _ABSENT:
        raise BuildError(
            "invalid_input", f"{_where(entry, old_id)}: key field {field!r} has no value"
        )
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return canonical_json(json.dumps(value))
    what = {bool: "a boolean", list: "a JSON array", dict: "a JSON object"}[type(value)]
    raise BuildError(
        "invalid_input",
        f"{_where(entry, old_id)}: key field {field!r} is {what}, not text or a number",
    )


def _column(entry: Entry, old_id: str, column: str, field: str, value: Any) -> str | None:
    if value is _ABSENT:
        return None
    if not isinstance(value, str):
        raise BuildError(
            "invalid_input",
            f"{_where(entry, old_id)}: field {field!r} fills {column}, which holds text, but its "
            f"value is {canonical_json(json.dumps(value))}",
        )
    return value


def _props(entry: Entry, old_id: str, text: object) -> dict[str, Any]:
    """A piece node's ``props``, which must be an I-JSON object (section 3.1).

    The piece is untrusted (section 3.8): the reading rules do not re-check its JSON text, so
    a value that has no canonical JSON form, such as an integer beyond 2^53 - 1, fails the build
    here with ``invalid_input`` rather than later, when values are compared or written.
    """
    if text is None:
        return {}
    try:
        canonical_json(str(text))
        props = json.loads(str(text))
    except ValueError as e:
        raise BuildError(
            "invalid_input", f"{_where(entry, old_id)}: props are not I-JSON (3.1): {e}"
        ) from None
    if not isinstance(props, dict):
        raise BuildError("invalid_input", f"{_where(entry, old_id)}: props are not a JSON object")
    return props


def map_node(entry: Entry, piece: Piece, row: Sequence[Any], *, positional: bool = False) -> Mapped:
    """Map one piece node, given as ``(nid, id, key, label, summary, props)``.

    ``positional`` says that the piece type's ``key_prop`` is NULL, so a key taken from the
    piece node's ``key`` is weak (section 7.2).
    """
    nid, old_id, key, label, summary, props_text = row
    props = _props(entry, old_id, props_text)
    columns = {"key": key, "label": label, "summary": summary}

    key_field = entry.fields.get(entry.key_prop, "key")
    written = _key_text(entry, old_id, key_field, _field(columns, props, key_field))
    stripped = written
    if entry.strip is not None and stripped.startswith(entry.strip):
        stripped = stripped[len(entry.strip) :]
    canonical = normalise(stripped, entry.steps)
    if canonical == "":
        raise BuildError(
            "invalid_input",
            f"{_where(entry, old_id)}: key {written!r} is empty after strip and normalisation",
        )

    texts: dict[str, str | None] = {}
    for column in TEXT_COLUMNS:
        field = entry.fields.get(column, column)
        texts[column] = _column(entry, old_id, column, field, _field(columns, props, field))
    mapped: dict[str, Any] = {}
    for prop, field in entry.fields.items():
        if prop == entry.key_prop or prop in TEXT_COLUMNS:
            continue
        value = _field(columns, props, field)
        if value is not _ABSENT:
            mapped[prop] = value
    return Mapped(
        entry=entry,
        piece=piece,
        nid=nid,
        old_id=old_id,
        key=canonical,
        written=written,
        label=texts["label"],
        summary=texts["summary"],
        props=mapped,
        weak=positional and key_field == "key",
    )


def map_nodes(inputs: Inputs) -> Iterator[Mapped]:
    """Step 2: every mapped piece node, in build order (pieces, then entries, then ``nid``)."""
    all_entries = entries(inputs.pattern)
    for piece in inputs.pieces:
        for entry in all_entries:
            if entry.piece != piece.name:
                continue
            positional = _positional(piece, entry.piece_type)
            rows = piece.file.query(
                "SELECT nid, id, key, label, summary, props FROM node WHERE type = ? ORDER BY nid",
                (entry.piece_type,),
            )
            for row in rows:
                yield map_node(entry, piece, row, positional=positional)


def _positional(piece: Piece, piece_type: str) -> bool:
    """Whether the piece declares node type ``piece_type`` with a NULL ``key_prop``."""
    rows = piece.file.query(
        "SELECT key_prop FROM type WHERE name = ? AND kind = 'node'", (piece_type,)
    )
    return any(key_prop is None for (key_prop,) in rows)
