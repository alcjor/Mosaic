"""SQLite tables to a tessera (plan M3.1; Specification 0.1 sections 3.4, 3.5, 4.1 and 4.3).

One SQLite database gives one tessera. Its one source is the database file (kind ``database``,
the SHA-256 of the file's bytes). Nothing is guessed: the settings name the tables to read and,
for each, its node type, label and summary columns, the columns that become props, their
conversions, and the foreign keys that become edges. They are recorded in ``header.settings``.

- **Tables.** Each table the settings name gives one node type (by default the table's name),
  and each of its rows one node. A table the settings do not name gives nothing. Only ordinary
  tables are read, never views, virtual or internal tables.
- **Keys.** A row's key is its primary key's value, as text: an integer in decimal, a real
  number in its canonical JSON form (section 3.1), text as written. The node id is
  ``<type>:<key>`` and the type's ``key_prop`` is the key column (section 3.4). A table needs a
  primary key of one column, or of two foreign keys (below); a key that is NULL, empty, a blob
  or holds ``;`` (which a locator value cannot hold, section 3.5) is refused, and so are two rows
  with the same key.
- **Values.** A prop column's value keeps its kind: an integer is a JSON integer (a string
  beyond +/-(2**53 - 1), section 3.1), a real a JSON number, text a string; NULL makes no prop.
  A column declares the kind its values have: ``integer``, ``number`` (integers and reals),
  ``text`` (also for a column with no values), or ``json`` when it holds text and numbers. A
  blob, a real that is not finite, text holding U+0000 and text that is not UTF-8 are refused,
  naming the row and the column. A real that is an integer beyond +/-(2**53 - 1) is written as
  an integer would be, so it is a string too. Labels and summaries are the column's value as
  text, NULL none.
- **Conversions** are the CSV builder's (``mosaic_build.tessera.convert``), declared per prop
  column. A conversion reads a value's text (as for keys); a value it cannot read keeps its kind
  and is listed in the :class:`Report` by ``<table>.<column>`` and the row's key.
- **Foreign keys.** A foreign key the settings name, by its one column, gives one edge type
  (the name the settings give it) from the table's type to the type of the table it references,
  which the settings must name too. Each non-NULL value is one edge from the row to the row it
  names, compared as SQLite compares them in a join; a value that names no row, or more than
  one, is refused. A column with more than one foreign key, or one of several columns, is
  refused.
- **Tables of two foreign keys** (plan M3.13, the maintainer's answer on #124). A table whose
  primary key is two columns, each a foreign key of one column, gives no node and no node type:
  each row gives one edge, from the row the first key column names to the row the second names
  (in key order), of the edge type its settings' ``edge`` names; the row's other columns are the
  edge's props, as a node's are. Its key is the two values' text joined by ``/``, so a value
  holding ``/`` is refused. Such a table takes ``edge`` and no other setting; any other key of
  several columns is refused, and a foreign key may not reference such a table.
- **Evidence.** One row per node, locator ``file=<name>;table=<table>;row=<key>``, and one per
  edge, ``file=<name>;table=<table>;row=<key>;field=<column>``, or for the row of a table of
  two foreign keys ``file=<name>;table=<table>;row=<first>/<second>``; method ``extracted``.
- **Reading.** The file is read once, as bytes; its hash and its content come from those bytes,
  which are opened in memory, read-only. The source file is never opened for writing and no
  file is made beside it (principle 8). A database with a ``-wal`` or ``-journal`` file beside
  it is refused: its content is not the file's bytes alone. So is a tessera or a mosaic (its
  ``application_id``, section 3.1), which a tessera's source never is (section 4.1, ADR-003).
- **JSON text** (``settings``, ``props``) is in the canonical form of RFC 8785 (section 3.1).

Errors name the file, and the table, row and column or the setting at fault. A setting at
fault, alone or for this database (a table or column it does not have, a foreign key it does
not declare), is a :class:`SettingError` that also gives the setting's place, so a settings
file's reader can name its line (``mosaic_build.tessera.sqlite_settings``). A file that cannot
be read is a ``ValueError`` naming it.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from mosaic_format.canonical_json import MAX_SAFE_INTEGER, canonical_json
from mosaic_format.writer import (
    Content,
    Edge,
    EdgeKey,
    Evidence,
    Header,
    Node,
    Sealed,
    Source,
    Type,
    seal,
)

from mosaic_build import __version__
from mosaic_build.tessera.convert import Conversion, check_conversions, prop_kinds

__all__ = [
    "Built",
    "Report",
    "SettingError",
    "Settings",
    "Table",
    "build",
    "check_settings",
    "content",
    "read",
]

PRODUCER = f"mosaic-sqlite/{__version__}"
"""Written as the header's ``producer`` and the producer of every evidence row."""

NODE_TYPE = re.compile(r"[A-Z][A-Za-z0-9]*")
"""Node type names (section 3.4)."""
EDGE_TYPE = re.compile(r"[a-z][a-z0-9_]*")
"""Edge type names (section 3.4)."""
MAGIC = b"SQLite format 3\x00"
"""The first 16 bytes of every SQLite 3 database file."""
LOGS = ("-wal", "-journal")
"""Files beside a database that hold content its own bytes do not."""

FILE_ID = 0x4D4F5341
"""``PRAGMA application_id`` of every tessera and mosaic (section 3.1)."""


type Where = tuple[str | int, ...]
"""A setting's place in the settings, key by key from ``tables``; a prop by its index."""


class SettingError(ValueError):
    """A setting the builder refuses, alone or for this database; ``where`` is its place."""

    def __init__(self, where: Where, message: str) -> None:
        super().__init__(message)
        self.where = where


class _Undecodable(bytes):
    """Text whose bytes are not UTF-8, kept so the row and column can be named."""


type _Value = int | float | str | bytes | None


def _text(raw: bytes) -> str | _Undecodable:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return _Undecodable(raw)


@dataclass(frozen=True)
class Table:
    """What one table gives: its node type (None: the table's name), the ``label`` and
    ``summary`` columns or None, the ``props`` columns, their conversions, and the foreign keys
    that become edges, each by its column, mapped to the edge type's name. For a table whose
    primary key is two foreign keys, ``edge`` names the edge type each row gives, and nothing
    else is set."""

    type: str | None = None
    label: str | None = None
    summary: str | None = None
    props: tuple[str, ...] = ()
    convert: Mapping[str, Conversion] = field(default_factory=dict)
    foreign_keys: Mapping[str, str] = field(default_factory=dict)
    edge: str | None = None

    def type_for(self, table: str) -> str:
        return table if self.type is None else self.type

    def as_json(self, table: str) -> dict[str, object]:
        if self.edge is not None:
            return {"edge": self.edge}
        value: dict[str, object] = {
            "type": self.type_for(table),
            "label": self.label,
            "summary": self.summary,
            "props": list(self.props),
        }
        if self.convert:
            value["convert"] = {c: v.as_json() for c, v in self.convert.items()}
        if self.foreign_keys:
            value["foreign_keys"] = dict(self.foreign_keys)
        return value


@dataclass(frozen=True)
class Settings:
    """What shapes a SQLite tessera: the tables to read, each by its name in the database."""

    tables: Mapping[str, Table] = field(default_factory=dict)

    def as_json(self) -> str:
        """The settings as canonical JSON text, for ``header.settings``; each table's type is
        written out, and ``convert`` and ``foreign_keys`` only when they name something."""
        return _json({"tables": {name: t.as_json(name) for name, t in self.tables.items()}})


@dataclass(frozen=True)
class Report:
    """What the builder could not do as asked, for its user; not part of the tessera.

    ``unconverted`` maps every converted column, as ``<table>.<column>`` in UTF-8 byte order, to
    the keys of the rows, in the table's key order, whose value its conversion could not read.
    """

    unconverted: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        """The number of values kept as they were, per converted column."""
        return {column: len(rows) for column, rows in self.unconverted.items()}


@dataclass(frozen=True)
class Built(Sealed):
    """The sealed tessera and the builder's report on it."""

    report: Report = field(default_factory=Report)


@dataclass(frozen=True)
class _ForeignKey:
    column: str
    edge: str
    parent: str
    parent_column: str


@dataclass(frozen=True)
class _EdgeTable:
    """A named table of two foreign keys: the edge type its rows give, its two key columns'
    foreign keys in key order, and its other columns, which are the edges' props."""

    name: str
    edge: str
    ends: tuple[_ForeignKey, _ForeignKey]
    props: tuple[str, ...]


@dataclass(frozen=True)
class _Shape:
    """A named table as the database declares it: its key column and its foreign keys."""

    name: str
    type: str
    key: str
    foreign_keys: tuple[_ForeignKey, ...]


def build(source: str | os.PathLike[str], out: str | os.PathLike[str], settings: Settings) -> Built:
    """Read the SQLite database ``source`` and write its tessera to the new file ``out``.

    Raises ``ValueError`` naming the file and the table, row, column or setting when the
    settings or the database cannot make a tessera; no file is left at ``out`` then. An existing
    ``out`` is never overwritten (``FileExistsError``).
    """
    made, report = read(source, settings)
    sealed = seal(out, made)
    return Built(sealed.path, sealed.knowledge_hash, sealed.vector_hash, report)


def content(source: str | os.PathLike[str], settings: Settings) -> Content:
    """The tessera's content for the SQLite database ``source``, ready to seal."""
    return read(source, settings)[0]


def read(source: str | os.PathLike[str], settings: Settings) -> tuple[Content, Report]:
    """The tessera's content for the SQLite database ``source`` and the builder's report."""
    path = Path(source)
    name = path.name
    check_settings(settings)
    if ";" in name:
        raise ValueError(
            f"{name!r}: a file name with ';' cannot be a locator value (section 3.5); rename it"
        )
    for log in LOGS:
        if path.with_name(name + log).exists():
            raise ValueError(
                f"{name}: has a {name + log} file beside it, so its content is not the file's "
                f"bytes alone; open it with SQLite once to finish its transactions"
            )
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ValueError(f"{path}: cannot be read ({e.strerror or e})") from None
    con = _open(name, data)
    try:
        shapes, edge_tables = _shapes(con, name, settings)
        made, report = _read(con, name, settings, shapes, edge_tables)
    finally:
        con.close()
    return (
        Content(
            header=Header(kind="tessera", producer=PRODUCER, settings=settings.as_json()),
            sources=[
                Source(id=name, kind="database", hash=hashlib.sha256(data).hexdigest(), path=name),
            ],
            types=made[0],
            nodes=made[1],
            edges=made[2],
            evidence=made[3],
        ),
        report,
    )


def check_settings(settings: Settings) -> None:
    """Refuse settings that cannot make a tessera whatever the database, naming the setting."""
    if not settings.tables:
        raise SettingError(("tables",), "settings: tables names no table; name at least one")
    types: dict[str, str] = {}
    edges: dict[str, str] = {}
    for table, t in settings.tables.items():
        at = f"settings: tables.{table}"
        if ";" in table:
            raise SettingError(
                ("tables", table), f"{at}: a table name with ';' cannot be a locator value (3.5)"
            )
        if t.edge is not None:
            _check_edge_table(table, t, edges)
            continue
        node_type = t.type_for(table)
        type_at: Where = ("tables", table) if t.type is None else ("tables", table, "type")
        typed = f"{at}: type" if t.type is None else f"{at}.type: type"
        if NODE_TYPE.fullmatch(node_type) is None:
            raise SettingError(
                type_at,
                f"{typed} {node_type!r} is not a node type name ^[A-Z][A-Za-z0-9]*$ (3.4)"
                + ("; set type" if t.type is None else ""),
            )
        if node_type in types:
            raise SettingError(
                type_at, f"{typed} {node_type!r} is already the type of table {types[node_type]!r}"
            )
        types[node_type] = table
        for i, p in enumerate(t.props):
            if p in t.props[:i]:
                raise SettingError(("tables", table, "props", i), f"{at}: props name {p!r} twice")
        try:
            check_conversions(t.props, t.convert)
        except ValueError as e:
            raise SettingError(
                ("tables", table, "convert"), f"{at}: {str(e).removeprefix('settings: ')}"
            ) from None
        for column, edge in t.foreign_keys.items():
            fk_at = ("tables", table, "foreign_keys", column)
            if ";" in column:
                raise SettingError(
                    fk_at, f"{at}: a column name with ';' cannot be a locator value (3.5)"
                )
            if EDGE_TYPE.fullmatch(edge) is None:
                raise SettingError(
                    fk_at,
                    f"{at}.foreign_keys.{column}: edge {edge!r} is not an edge type name "
                    f"^[a-z][a-z0-9_]*$ (3.4)",
                )
            if edge in edges:
                raise SettingError(
                    fk_at,
                    f"{at}.foreign_keys.{column}: edge {edge!r} is already the edge of "
                    f"{edges[edge]}; each foreign key has its own edge type",
                )
            edges[edge] = f"tables.{table}.foreign_keys.{column}"


_NODE_SETTINGS = ("type", "label", "summary", "props", "convert", "foreign_keys")
"""A table's settings that shape nodes, which a table that gives edges does not take."""


def _check_edge_table(table: str, t: Table, edges: dict[str, str]) -> None:
    at = f"settings: tables.{table}"
    given = {
        "type": t.type is not None,
        "label": t.label is not None,
        "summary": t.summary is not None,
        "props": bool(t.props),
        "convert": bool(t.convert),
        "foreign_keys": bool(t.foreign_keys),
    }
    for setting in _NODE_SETTINGS:
        if given[setting]:
            raise SettingError(
                ("tables", table, setting),
                f"{at}.{setting}: a table that gives edges (edge) takes no {setting}; its rows "
                f"are edges, and its other columns their props",
            )
    edge = str(t.edge)
    where: Where = ("tables", table, "edge")
    if EDGE_TYPE.fullmatch(edge) is None:
        raise SettingError(
            where, f"{at}.edge: edge {edge!r} is not an edge type name ^[a-z][a-z0-9_]*$ (3.4)"
        )
    if edge in edges:
        raise SettingError(
            where,
            f"{at}.edge: edge {edge!r} is already the edge of {edges[edge]}; each table and "
            f"foreign key has its own edge type",
        )
    edges[edge] = f"tables.{table}.edge"


def _open(name: str, data: bytes) -> sqlite3.Connection:
    """The database ``data`` holds, opened in memory and read-only."""
    if not data.startswith(MAGIC):
        raise ValueError(f"{name}: is not a SQLite database")
    image = bytearray(data)
    if len(image) >= 20 and image[18] == image[19] == 2:
        # A database in write-ahead log mode with no log beside it: its pages are all in the
        # file. SQLite opens such an image in memory only in rollback mode.
        image[18] = image[19] = 1
    if len(image) >= 72 and int.from_bytes(image[68:72], "big") == FILE_ID:
        raise ValueError(
            f"{name}: is a tessera or a mosaic, which a tessera's source never is (4.1, ADR-003)"
        )
    con = sqlite3.connect(":memory:")
    con.text_factory = _text
    try:
        con.deserialize(bytes(image))
        con.execute("PRAGMA query_only = ON")
        con.execute("SELECT count(*) FROM sqlite_schema").fetchone()
    except sqlite3.DatabaseError as e:
        con.close()
        raise ValueError(f"{name}: is not a SQLite database ({e})") from None
    return con


def _q(identifier: str) -> str:
    """An SQL identifier, quoted; only names the database itself declares reach SQL."""
    return '"' + identifier.replace('"', '""') + '"'


type _Declared = dict[int, list[tuple[str, str, str | None]]]
"""A table's foreign keys by id: each one's columns as (column, parent table, parent column)."""


def _shapes(
    con: sqlite3.Connection, name: str, settings: Settings
) -> tuple[dict[str, _Shape], dict[str, _EdgeTable]]:
    """Each named table's key and foreign keys, checked against the settings: the tables whose
    rows are nodes, and the tables of two foreign keys, whose rows are edges."""
    tables = {
        str(n): str(sql or "")
        for n, sql in con.execute(
            "SELECT name, sql FROM sqlite_schema"
            " WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
        )
    }
    # Every named table, its key and what its rows give first: a foreign key may reference any.
    found: dict[str, tuple[list[str], list[str], _Declared]] = {}
    gives_edges: set[str] = set()
    for table, t in settings.tables.items():
        at = f"{name}: table {table!r}"
        if table not in tables or tables[table].lstrip().upper().startswith("CREATE VIRTUAL"):
            raise SettingError(
                ("tables", table),
                f"{at} is not a table of the database (settings: tables.{table})",
            )
        columns, key = _columns(con, table)
        declared: _Declared = {}
        for row in con.execute(f"PRAGMA foreign_key_list({_q(table)})"):
            declared.setdefault(int(row[0]), []).append((str(row[3]), str(row[2]), row[4]))
        found[table] = (columns, key, declared)
        if not key:
            raise ValueError(f"{at} has no primary key; a row's key is its primary key")
        if len(key) == 1:
            if t.edge is not None:
                raise SettingError(
                    ("tables", table, "edge"),
                    f"{at} has a primary key of one column ({key[0]}), so its rows are nodes; "
                    f"edge is for a table whose primary key is two foreign keys "
                    f"(settings: tables.{table}.edge)",
                )
            continue
        if len(key) != 2 or not all(_single(declared, c) for c in key):
            raise ValueError(
                f"{at} has a primary key of {len(key)} columns ({', '.join(key)}); a row's key "
                f"is a primary key of one column, or of two columns that are each a foreign key "
                f"(each row then gives an edge)"
            )
        if t.edge is None:
            raise SettingError(
                ("tables", table),
                f"{at} has a primary key of two foreign keys ({', '.join(key)}), so each row "
                f"gives an edge; set edge to name its edge type (settings: tables.{table}.edge)",
            )
        gives_edges.add(table)

    def parent_of(at: str, where: Where, column: str, declared: _Declared) -> _ForeignKey:
        """The table and column the one foreign key of ``column`` references, checked."""
        ((_, parent, to),) = next(fk for fk in declared.values() if fk[0][0] == column)
        if parent not in settings.tables:
            raise SettingError(
                where,
                f"{at} references table {parent!r}, which the settings do not name "
                f"(names compare exactly); an edge needs the row it names in the tessera",
            )
        if parent in gives_edges:
            raise SettingError(
                where, f"{at} references table {parent!r}, whose rows are edges, not nodes"
            )
        parent_columns, parent_key, _ = found[parent]
        # A foreign key that names no column references its table's primary key.
        to = parent_key[0] if to is None else str(to)
        if to not in parent_columns:
            raise SettingError(
                where, f"{at} references column {to!r} of table {parent!r}, which has none"
            )
        return _ForeignKey(column, "", parent, to)

    shapes: dict[str, _Shape] = {}
    edge_tables: dict[str, _EdgeTable] = {}
    for table, t in settings.tables.items():
        at = f"{name}: table {table!r}"
        columns, key, declared = found[table]
        if table in gives_edges:
            first, second = (
                parent_of(f"{at}: key column {c!r}", ("tables", table), c, declared) for c in key
            )
            props = tuple(c for c in columns if c not in key)
            edge_tables[table] = _EdgeTable(table, str(t.edge), (first, second), props)
            continue
        named: list[tuple[Where, str | None]] = [(("label",), t.label), (("summary",), t.summary)]
        named += [(("props", i), p) for i, p in enumerate(t.props)]
        named += [(("foreign_keys", c), c) for c in t.foreign_keys]
        for setting, column in named:
            if column is not None and column not in columns:
                shown = ".".join(str(s) for s in setting if isinstance(s, str))
                raise SettingError(
                    ("tables", table, *setting),
                    f"{at} has no column {column!r} (settings: tables.{table}.{shown})",
                )
        foreign_keys: list[_ForeignKey] = []
        for column, edge in t.foreign_keys.items():
            fk_at = ("tables", table, "foreign_keys", column)
            where = f"{at}: column {column!r} (settings: tables.{table}.foreign_keys.{column})"
            fks = [fk for fk in declared.values() if any(c == column for c, _, _ in fk)]
            if not fks:
                raise SettingError(fk_at, f"{where} has no foreign key in the database")
            if len(fks) > 1:
                raise SettingError(
                    fk_at, f"{where} has {len(fks)} foreign keys; name a column with one"
                )
            if len(fks[0]) > 1:
                raise SettingError(
                    fk_at, f"{where} is one of {len(fks[0])} columns of a foreign key"
                )
            fk = parent_of(where, fk_at, column, declared)
            foreign_keys.append(_ForeignKey(column, edge, fk.parent, fk.parent_column))
        shapes[table] = _Shape(table, t.type_for(table), key[0], tuple(foreign_keys))
    return shapes, edge_tables


def _single(declared: _Declared, column: str) -> bool:
    """Whether ``column`` has exactly one foreign key, and that one of this column alone."""
    fks = [fk for fk in declared.values() if any(c == column for c, _, _ in fk)]
    return len(fks) == 1 and len(fks[0]) == 1


def _columns(con: sqlite3.Connection, table: str) -> tuple[list[str], list[str]]:
    """A table's columns and its primary key's columns, in key order."""
    # table_xinfo also lists generated columns (hidden 2 and 3); 1 is a virtual table's hidden one.
    info = [r for r in con.execute(f"PRAGMA table_xinfo({_q(table)})") if int(r[6]) != 1]
    columns = [str(row[1]) for row in info]
    key = [str(row[1]) for row in sorted(info, key=lambda r: int(r[5])) if int(row[5]) > 0]
    return columns, key


def _text_of(value: _Value) -> str:
    """A value's text: an integer in decimal, a real in canonical JSON form, text as is."""
    match value:
        case bool():
            raise TypeError("SQLite has no boolean values")
        case int():
            return str(value)
        case float():
            return canonical_json(json.dumps(value))
        case str():
            return value
        case _:
            raise TypeError(f"no text for {value!r}")


def _check(at: str, column: str, value: _Value) -> None:
    """Refuse a value no file can hold."""
    if isinstance(value, _Undecodable):
        raise ValueError(f"{at}: {column!r} holds text that is not UTF-8 (3.1)")
    if isinstance(value, bytes):
        raise ValueError(f"{at}: {column!r} holds a blob, which a tessera cannot hold as a value")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{at}: {column!r} holds {value!r}, which JSON cannot hold (3.1)")
    if isinstance(value, str) and "\x00" in value:
        raise ValueError(f"{at}: {column!r} contains U+0000, which text never holds (3.1)")


def _prop(value: int | float | str) -> object:
    if isinstance(value, int) and abs(value) > MAX_SAFE_INTEGER:
        return str(value)  # section 3.1
    if isinstance(value, float) and value.is_integer() and MAX_SAFE_INTEGER < abs(value) < 1e21:
        return _text_of(value)  # written as an integer, so stored as a string too (3.1)
    return value


def _kind(values: Iterable[_Value]) -> str:
    """The kind a column declares from the values it holds."""
    seen = {type(v) for v in values if v is not None}
    if not seen or seen == {str}:
        return "text"
    if seen == {int}:
        return "integer"
    if str not in seen:
        return "number"
    return "json"


def _read(
    con: sqlite3.Connection,
    name: str,
    settings: Settings,
    shapes: Mapping[str, _Shape],
    edge_tables: Mapping[str, _EdgeTable],
) -> tuple[tuple[list[Type], list[Node], list[Edge], list[Evidence]], Report]:
    types: list[Type] = []
    nodes: list[Node] = []
    edges: list[Edge] = []
    evidence: list[Evidence] = []
    unconverted: dict[str, list[str]] = {}
    for table, t in settings.tables.items():
        if table in edge_tables:
            continue
        shape = shapes[table]
        wanted = list(
            dict.fromkeys([c for c in (t.label, t.summary) if c is not None] + [*t.props])
        )
        select = ", ".join(_q(c) for c in [shape.key, *wanted])
        rows = con.execute(f"SELECT {select} FROM {_q(table)} ORDER BY 1").fetchall()
        seen: set[str] = set()
        values: dict[str, list[_Value]] = {p: [] for p in t.props}
        for c in t.convert:
            unconverted[f"{table}.{c}"] = []
        for row in rows:
            key = _key(name, table, shape.key, row[0], seen)
            at = f"{name}: table {table!r} row {key}"
            cells = dict(zip(wanted, row[1:], strict=True))
            for column, value in cells.items():
                _check(at, column, value)
            props: dict[str, object] = {}
            for p in t.props:
                value = cells[p]
                if value is None:
                    continue
                conversion = t.convert.get(p)
                if conversion is None:
                    values[p].append(value)
                    props[p] = _prop(value)
                    continue
                converted = conversion.read(p, _text_of(value))
                if converted is None:
                    props[conversion.fallback(p)] = _prop(value)
                    unconverted[f"{table}.{p}"].append(key)
                else:
                    props.update(converted)
            node_id = f"{shape.type}:{key}"
            nodes.append(
                Node(
                    id=node_id,
                    type=shape.type,
                    key=key,
                    label=_label(cells, t.label),
                    summary=_label(cells, t.summary),
                    props=_json(props) if props else None,
                )
            )
            evidence.append(_evidence(node_id, name, f"file={name};table={table};row={key}"))
        kinds = prop_kinds(t.props, t.convert)
        kinds.update({p: _kind(values[p]) for p in t.props if p not in t.convert})
        types.append(Type(name=shape.type, kind="node", key_prop=shape.key, props=_json(kinds)))
    for table in settings.tables:
        if table in edge_tables:
            _edge_rows(con, name, edge_tables[table], shapes, (types, edges, evidence))
            continue
        shape = shapes[table]
        for fk in shape.foreign_keys:
            parent = shapes[fk.parent]
            types.append(Type(name=fk.edge, kind="edge", from_type=shape.type, to_type=parent.type))
            for key, dst in _references(con, name, table, (shape.key,), fk, parent):
                edge = Edge(type=fk.edge, src=f"{shape.type}:{key}", dst=f"{parent.type}:{dst}")
                edges.append(edge)
                locator = f"file={name};table={table};row={key};field={fk.column}"
                evidence.append(_evidence(edge.key, name, locator))
    report = Report(
        {c: tuple(unconverted[c]) for c in sorted(unconverted, key=lambda c: c.encode("utf-8"))}
    )
    return (types, nodes, edges, evidence), report


def _key(name: str, table: str, column: str, value: _Value, seen: set[str]) -> str:
    """A row's key from its primary key value; refused when no node id can hold it."""
    return _unique(name, table, _key_text(name, table, column, value), seen)


def _unique(name: str, table: str, key: str, seen: set[str]) -> str:
    if key in seen:
        raise ValueError(
            f"{name}: table {table!r}: two rows have the key {key!r}; "
            f"node ids are unique within a tessera (4.1)"
        )
    seen.add(key)
    return key


def _key_text(name: str, table: str, column: str, value: _Value) -> str:
    """A key column's value as text; refused when no locator can hold it (section 3.5)."""
    at = f"{name}: table {table!r}"
    if value is None or (isinstance(value, bytes) and not isinstance(value, _Undecodable)):
        what = "NULL" if value is None else "a blob"
        raise ValueError(f"{at}: a row's key column {column!r} is {what}; a key is text")
    _check(at, column, value)
    key = _text_of(value)
    if key == "":
        raise ValueError(f"{at}: a row's key column {column!r} is empty")
    if ";" in key:
        raise ValueError(
            f"{at}: key {key!r} holds ';', which a locator value cannot hold (section 3.5)"
        )
    return key


def _edge_rows(
    con: sqlite3.Connection,
    name: str,
    table: _EdgeTable,
    shapes: Mapping[str, _Shape],
    into: tuple[list[Type], list[Edge], list[Evidence]],
) -> None:
    """The edges a table of two foreign keys gives, one per row, with their evidence."""
    types, edges, evidence = into
    first, second = table.ends
    keys = (first.column, second.column)
    select = ", ".join(_q(c) for c in [*keys, *table.props])
    rows = con.execute(f"SELECT {select} FROM {_q(table.name)} ORDER BY 1, 2").fetchall()
    seen: set[str] = set()
    values: dict[str, list[_Value]] = {p: [] for p in table.props}
    props_of: dict[str, str | None] = {}
    for row in rows:
        parts = [_key_text(name, table.name, c, v) for c, v in zip(keys, row[:2], strict=True)]
        for column, part in zip(keys, parts, strict=True):
            if "/" in part:
                raise ValueError(
                    f"{name}: table {table.name!r}: key column {column!r} is {part!r}, which "
                    f"holds '/', the separator of a key of two foreign keys"
                )
        key = _unique(name, table.name, "/".join(parts), seen)
        at = f"{name}: table {table.name!r} row {key}"
        props: dict[str, object] = {}
        for column, value in zip(table.props, row[2:], strict=True):
            _check(at, column, value)
            if value is not None:
                values[column].append(value)
                props[column] = _prop(value)
        props_of[key] = _json(props) if props else None
    srcs, dsts = (
        dict(_references(con, name, table.name, keys, fk, shapes[fk.parent])) for fk in table.ends
    )
    src_type, dst_type = shapes[first.parent].type, shapes[second.parent].type
    kinds = {p: _kind(values[p]) for p in table.props}
    types.append(
        Type(name=table.edge, kind="edge", from_type=src_type, to_type=dst_type, props=_json(kinds))
    )
    pairs: dict[tuple[str, str], str] = {}
    for key, edge_props in props_of.items():
        src, dst = srcs[key], dsts[key]
        if (src, dst) in pairs:
            raise ValueError(
                f"{name}: table {table.name!r}: rows {pairs[src, dst]} and {key} both name "
                f"{src_type}:{src} and {dst_type}:{dst}; each row gives its own edge"
            )
        pairs[src, dst] = key
        edge = Edge(
            type=table.edge,
            src=f"{src_type}:{src}",
            dst=f"{dst_type}:{dst}",
            props=edge_props,
        )
        edges.append(edge)
        evidence.append(_evidence(edge.key, name, f"file={name};table={table.name};row={key}"))


def _references(
    con: sqlite3.Connection,
    name: str,
    table: str,
    keys: tuple[str, ...],
    fk: _ForeignKey,
    parent: _Shape,
) -> list[tuple[str, str]]:
    """Each row's key (its ``keys`` columns' text joined by ``/``) and the key of the row its
    foreign key value names, in key order; NULL names none."""
    columns = ", ".join(f"c.{_q(k)}" for k in keys)
    order = ", ".join(str(i) for i in range(1, len(keys) + 3))
    sql = (
        f"SELECT {columns}, c.{_q(fk.column)}, p.{_q(parent.key)}"
        f" FROM {_q(table)} AS c LEFT JOIN {_q(parent.name)} AS p"
        f" ON c.{_q(fk.column)} = p.{_q(fk.parent_column)}"
        f" WHERE c.{_q(fk.column)} IS NOT NULL ORDER BY {order}"
    )
    found: dict[str, list[str]] = {}
    values: dict[str, _Value] = {}
    for row in con.execute(sql):
        *child, value, dst = row
        key = "/".join(_text_of(v) for v in child)
        values[key] = value
        targets = found.setdefault(key, [])
        if dst is not None:
            targets.append(_text_of(dst))
    pairs: list[tuple[str, str]] = []
    for key, targets in found.items():
        at = f"{name}: table {table!r} row {key}: {fk.column!r}"
        if not targets:
            raise ValueError(
                f"{at} is {values[key]!r}, but table {parent.name!r} has no row with "
                f"{fk.parent_column!r} = {values[key]!r}"
            )
        if len(targets) > 1:
            raise ValueError(
                f"{at} is {values[key]!r}, which {len(targets)} rows of table {parent.name!r} "
                f"have in {fk.parent_column!r}"
            )
        pairs.append((key, targets[0]))
    return pairs


def _label(cells: Mapping[str, _Value], column: str | None) -> str | None:
    if column is None or cells[column] is None:
        return None
    return _text_of(cells[column])


def _evidence(subject: str | EdgeKey, source: str, locator: str) -> Evidence:
    return Evidence(
        subject=subject, source=source, locator=locator, method="extracted", producer=PRODUCER
    )


def _json(value: Mapping[str, object]) -> str:
    """Canonical JSON text (RFC 8785, section 3.1) of an object of JSON values."""
    return canonical_json(json.dumps(value, ensure_ascii=False, allow_nan=False))
