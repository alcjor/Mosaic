"""The knowledge hash and the vector hash (Specification 0.1, sections 3.6 and 3.7).

The knowledge hash is the SHA-256 of a canonical byte string built part by part from the
hashed tables. Each part starts with ``#<part>`` and a newline; each row is its column values
encoded as SQLite's ``quote()`` would, joined by commas, followed by a newline. ``confidence``
is encoded as ``quote(CAST(round(confidence*1000000) AS INTEGER))``.

Two implementations produce that byte string and must agree byte for byte:

- :func:`encode_knowledge` streams the rows and encodes every value in Python;
- :func:`encode_knowledge_sql` runs :data:`KNOWLEDGE_SQL`, which builds every line in SQL.

Both take an open :class:`sqlite3.Connection` and a ``sink`` that receives the bytes in order,
so a file of any size is hashed without holding its encoding in memory.
"""

import hashlib
import sqlite3
from collections.abc import Callable
from typing import NamedTuple

Sink = Callable[[bytes], object]
"""Receives the canonical bytes in order, such as ``hashlib.sha256().update``."""


class Part(NamedTuple):
    """One part of the knowledge hash: its table, columns in order, and row order."""

    name: str
    columns: tuple[str, ...]
    order: str


PARTS: tuple[Part, ...] = (
    Part("header", ("format_version", "kind"), "one"),
    Part("source", ("sid", "id", "kind", "hash", "notice"), "sid"),
    Part(
        "type",
        ("name", "kind", "description", "key_prop", "from_type", "to_type", "props"),
        "name",
    ),
    Part("node", ("nid", "id", "type", "key", "label", "summary", "props"), "nid"),
    Part("edge", ("eid", "type", "src", "dst", "qualifier", "props"), "eid"),
    Part("alias", ("text", "nid", "origin"), "text COLLATE NOCASE, nid"),
    Part(
        "evidence",
        (
            "evid",
            "nid",
            "eid",
            "prop",
            "sid",
            "locator",
            "method",
            "producer",
            "confidence",
            "via",
        ),
        "evid",
    ),
    Part("snippet", ("evid", "text"), "evid"),
    Part("mention", ("mid", "text", "locator", "nid", "role", "kind"), "mid"),
    Part("source_text", ("sid", "text"), "sid"),
    Part("external_ref", ("xid", "nid", "system", "kind", "locator", "sid"), "xid"),
)
"""The parts of the knowledge hash, in order (section 3.6). Each part is a table of that name."""

CONFIDENCE = "confidence"
"""The one column encoded as a rounded integer instead of with plain ``quote()``."""

VECTOR_BYTES = 48
"""Length of one stored vector: 384 sign bits (section 3.7)."""

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_EXACT = 4503599627370496.0  # 2**52: a double this large has no fractional part


def _sql_value(part: str, column: str) -> str:
    if part == "evidence" and column == CONFIDENCE:
        return "quote(CAST(round(confidence*1000000) AS INTEGER))"
    return f"quote({column})"


def _part_sql(index: int, part: Part) -> str:
    heading = f"SELECT {index} AS p, 0 AS k, '#{part.name}' || char(10) AS line"
    values = " || ',' || ".join(_sql_value(part.name, c) for c in part.columns)
    rows = (
        f"SELECT {index}, row_number() OVER (ORDER BY {part.order}), "
        f"{values} || char(10) FROM {part.name}"
    )
    return f"{heading}\nUNION ALL\n{rows}"


KNOWLEDGE_SQL = (
    "SELECT CAST(line AS BLOB) FROM (\n"
    + "\nUNION ALL\n".join(_part_sql(i, part) for i, part in enumerate(PARTS))
    + "\n) ORDER BY p, k"
)
"""One query whose rows, concatenated, are the canonical byte string of section 3.6.

It needs only ``quote()``, ``round()``, ``CAST`` and ``row_number()`` (SQLite 3.25 or later).
"""


def _quote_text(value: str) -> bytes:
    # quote() reads text as a C string: it stops at the first U+0000. The text factory below
    # keeps bytes that are not valid UTF-8 as surrogates, so they round-trip unchanged.
    raw = value.encode("utf-8", "surrogateescape").split(b"\x00", 1)[0]
    return b"'" + raw.replace(b"'", b"''") + b"'"


def _where(part: str, row: int, column: str) -> str:
    return f"part {part!r}, row {row} in canonical order, column {column!r}"


def quote(value: object, *, where: str = "value") -> bytes:
    """Encode one stored value as SQLite's ``quote()`` does, for every value the hash takes.

    NULL is ``NULL``, an integer is decimal, text is single-quoted with inner quotes doubled
    and blobs are ``X'<uppercase hex>'``. A REAL outside ``confidence`` has no portable
    ``quote()`` form, so it is refused; ``where`` names the value in that error.
    """
    if value is None:
        return b"NULL"
    if isinstance(value, bool):
        raise TypeError(f"{where}: {value!r} is not a value SQLite stores")
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, str):
        return _quote_text(value)
    if isinstance(value, bytes):
        return b"X'" + value.hex().upper().encode("ascii") + b"'"
    if isinstance(value, float):
        raise ValueError(
            f"{where}: REAL value {value!r} has no portable quote() form; "
            "only confidence may be REAL"
        )
    raise TypeError(f"{where}: {type(value).__name__} is not a value SQLite stores")


def quote_confidence(value: object, *, where: str = "confidence") -> bytes:
    """Encode ``confidence`` as ``quote(CAST(round(confidence*1000000) AS INTEGER))``.

    ``round()`` with no digits rounds half away from zero (SQLite's ``roundFunc``), and
    ``CAST`` to INTEGER truncates toward zero and saturates at the 64-bit limits.
    """
    if value is None:
        return b"NULL"
    # The column has REAL affinity, so SQLite returns every number stored in it as a REAL.
    if not isinstance(value, float):
        raise ValueError(f"{where}: {value!r} is not REAL; confidence must be REAL or NULL")
    r = value * 1000000.0
    if -_EXACT <= r <= _EXACT:
        r = float(int(r + (-0.5 if r < 0 else 0.5)))
    whole = _INT64_MAX if r >= 2.0**63 else _INT64_MIN if r <= -(2.0**63) else int(r)
    return str(whole).encode("ascii")


def _surrogate_text(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def encode_knowledge(con: sqlite3.Connection, sink: Sink) -> None:
    """Stream the canonical byte string of section 3.6 into ``sink``, encoding in Python.

    Rows are read in the part's row order; ``alias`` sorts by its declared ``NOCASE``
    collation, then ``nid``. The connection's ``text_factory`` is replaced while reading and
    restored afterwards.
    """
    saved = con.text_factory
    con.text_factory = _surrogate_text
    try:
        for part in PARTS:
            sink(b"#" + part.name.encode("ascii") + b"\n")
            columns = ", ".join(part.columns)
            query = f"SELECT {columns} FROM {part.name} ORDER BY {part.order}"
            for number, row in enumerate(con.execute(query), start=1):
                values = [
                    quote_confidence(v, where=_where(part.name, number, c))
                    if part.name == "evidence" and c == CONFIDENCE
                    else quote(v, where=_where(part.name, number, c))
                    for c, v in zip(part.columns, row, strict=True)
                ]
                sink(b",".join(values) + b"\n")
    finally:
        con.text_factory = saved


def encode_knowledge_sql(con: sqlite3.Connection, sink: Sink) -> None:
    """Stream the canonical byte string of section 3.6 into ``sink``, built by SQL alone."""
    for (line,) in con.execute(KNOWLEDGE_SQL):
        sink(line)


def knowledge_hash(con: sqlite3.Connection) -> str:
    """The knowledge hash of the open file: SHA-256 as 64 lowercase hex characters."""
    digest = hashlib.sha256()
    encode_knowledge(con, digest.update)
    return digest.hexdigest()


def knowledge_hash_sql(con: sqlite3.Connection) -> str:
    """The knowledge hash computed from :data:`KNOWLEDGE_SQL`; equal to :func:`knowledge_hash`."""
    digest = hashlib.sha256()
    encode_knowledge_sql(con, digest.update)
    return digest.hexdigest()


def vector_hash(con: sqlite3.Connection) -> str | None:
    """The vector hash of section 3.7, or None when the file holds no vectors.

    It is the SHA-256 of the 48-byte ``bits`` values concatenated in ``nid`` order. A value
    that is not a 48-byte blob is refused, naming the node it belongs to.
    """
    digest = hashlib.sha256()
    count = 0
    query = (
        "SELECT n.id, v.bits FROM vector AS v LEFT JOIN node AS n ON n.nid = v.nid ORDER BY v.nid"
    )
    for count, (node, bits) in enumerate(con.execute(query), start=1):
        if not isinstance(bits, bytes) or len(bits) != VECTOR_BYTES:
            shown = f"{len(bits)}-byte blob" if isinstance(bits, bytes) else type(bits).__name__
            raise ValueError(
                f"vector of node {node!r} (row {count} in nid order): "
                f"bits is a {shown}, not a {VECTOR_BYTES}-byte blob"
            )
        digest.update(bits)
    return digest.hexdigest() if count else None
