"""CSV rows to a tessera (Specification 0.1, section 4; issue #11).

One CSV file gives one tessera. Its one source is the file (kind ``file``, the SHA-256 of the
file's bytes); each data row gives one node of one type, with evidence
``file=<name>;row=<n>``, ``row`` counting data rows from 1 after the header row, method
``extracted``. Nothing is guessed: the settings name the type, the key, label and summary
columns and the columns that become props, and they are recorded in ``header.settings``.

- **Keys.** With a key column, a row's key is that cell as written and the node id is
  ``<type>:<key>``; the type's ``key_prop`` is the column. Without one, the key is the row
  number (a weak id, docs/design.md ADR-002) and ``key_prop`` is NULL. A key must be non-empty
  and unique: node ids are unique within a tessera (section 4.1).
- **Cells.** Values are text, kept exactly as the CSV reader gives them (no trimming: that is
  the pattern's ``strip``, section 5.2). An empty cell makes no prop, label or summary, since a
  CSV cannot tell an empty value from a missing one. Props are ``text`` unless converted.
- **Conversions** (issue #13) are declared per prop column in ``Settings.convert``, never
  guessed: ``Date`` (the given formats, tried in order, to ISO ``YYYY-MM-DD``), ``Quantity``
  (a number and a unit from a declared unit map, as two props), ``Integer``, ``Number`` and
  ``Boolean`` (explicit spellings). A converter ignores white space around the value. A value
  it cannot read stays as text, exactly as written, and its row is listed in the build's
  ``Report``. The kinds declared in ``type.props`` follow the conversions (section 3.4). Month
  names are English and digits ASCII whatever the locale: nothing here reads the locale.
- **Reading.** The bytes are decoded with the given encoding (a leading byte order mark is
  dropped) and parsed with Python's ``csv`` module, strict quoting, ``"`` as the quote and
  doubled quotes as escapes. A quoted line break stays inside its cell; a blank line is no
  row. A row with a different number of fields than the header is refused.
- **JSON text** (``settings``, ``props``) is in the canonical form of RFC 8785 (section 3.1).

Errors name the file and the row, line or column at fault. The source is only read.
"""

import codecs
import csv
import hashlib
import io
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mosaic_format.canonical_json import canonical_json
from mosaic_format.writer import Content, Evidence, Header, Node, Sealed, Source, Type, seal

from mosaic_build import __version__
from mosaic_build.tessera.convert import (
    Boolean,
    Conversion,
    Date,
    Integer,
    Number,
    Quantity,
    check_conversions,
    prop_kinds,
)

__all__ = [
    "Boolean",
    "Built",
    "Conversion",
    "Date",
    "Integer",
    "Number",
    "Quantity",
    "Report",
    "Settings",
    "build",
    "content",
    "read",
]

PRODUCER = f"mosaic-csv/{__version__}"
"""Written as the header's ``producer`` and the producer of every evidence row."""

NODE_TYPE = re.compile(r"[A-Z][A-Za-z0-9]*")
"""Node type names (section 3.4)."""


@dataclass(frozen=True)
class Settings:
    """What shapes a CSV tessera; recorded in ``header.settings`` as given.

    ``key``, ``label`` and ``summary`` name a column or are None; ``props`` names the columns
    that become props. ``key = None`` keys rows by their position. ``convert`` maps a prop
    column to its conversion; other props are text.
    """

    type: str = "Row"
    key: str | None = None
    label: str | None = None
    summary: str | None = None
    props: tuple[str, ...] = ()
    encoding: str = "utf-8"
    delimiter: str = ","
    convert: Mapping[str, Conversion] = field(default_factory=dict)

    def as_json(self) -> str:
        """The settings as canonical JSON text, for ``header.settings``.

        ``convert`` is recorded only when it names a conversion: no conversions and an empty
        map are the same settings.
        """
        value: dict[str, object] = {
            "type": self.type,
            "key": self.key,
            "label": self.label,
            "summary": self.summary,
            "props": list(self.props),
            "encoding": self.encoding,
            "delimiter": self.delimiter,
        }
        if self.convert:
            value["convert"] = {c: v.as_json() for c, v in self.convert.items()}
        return _json(value)


@dataclass(frozen=True)
class Report:
    """What the builder could not do as asked, for its user; not part of the tessera.

    ``unconverted`` maps every converted column, in UTF-8 byte order, to the data rows (from 1)
    whose value its conversion could not read and so kept as text.
    """

    unconverted: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        """The number of values kept as text, per converted column."""
        return {column: len(rows) for column, rows in self.unconverted.items()}


@dataclass(frozen=True)
class Built(Sealed):
    """The sealed tessera and the builder's report on it."""

    report: Report = field(default_factory=Report)


def build(source: str | os.PathLike[str], out: str | os.PathLike[str], settings: Settings) -> Built:
    """Read the CSV file ``source`` and write its tessera to the new file ``out``.

    Raises ``ValueError`` naming the file and the row, line or column when the settings or the
    file cannot make a tessera; no file is left at ``out`` then. An existing ``out`` is never
    overwritten (``FileExistsError``). The result is the sealed file with the builder's report.
    """
    made, report = read(source, settings)
    sealed = seal(out, made)
    return Built(sealed.path, sealed.knowledge_hash, sealed.vector_hash, report)


def content(source: str | os.PathLike[str], settings: Settings) -> Content:
    """The tessera's content for the CSV file ``source``, ready to seal."""
    return read(source, settings)[0]


def read(source: str | os.PathLike[str], settings: Settings) -> tuple[Content, Report]:
    """The tessera's content for the CSV file ``source`` and the builder's report on it."""
    path = Path(source)
    name = path.name
    _check_settings(settings)
    if ";" in name:
        raise ValueError(
            f"{name!r}: a file name with ';' cannot be a locator value (section 3.5); rename it"
        )
    data = path.read_bytes()
    header, rows = _parse(name, _decode(name, data, settings.encoding), settings.delimiter)
    columns = _columns(name, header, settings)

    nodes: list[Node] = []
    evidence: list[Evidence] = []
    seen: dict[str, int] = {}
    unconverted: dict[str, list[int]] = {c: [] for c in settings.convert}
    for n, (line, cells) in enumerate(rows, start=1):
        where = f"{name}: row {n} (line {line})"
        if len(cells) != len(header):
            raise ValueError(
                f"{where}: has {len(cells)} field{'s' if len(cells) != 1 else ''}, "
                f"the header has {len(header)}"
            )
        for column, cell in zip(header, cells, strict=True):
            if "\x00" in cell:
                raise ValueError(
                    f"{where}: column {column!r} contains U+0000, which text never holds (3.1)"
                )
        key = str(n) if settings.key is None else cells[columns[settings.key]]
        if settings.key is not None:
            if key == "":
                raise ValueError(f"{where}: key column {settings.key!r} is empty")
            if key in seen:
                raise ValueError(
                    f"{name}: rows {seen[key]} and {n} have the same key {key!r} in column "
                    f"{settings.key!r}; node ids are unique within a tessera (section 4.1)"
                )
        seen[key] = n
        node_id = f"{settings.type}:{key}"
        props: dict[str, object] = {}
        for p in settings.props:
            cell = cells[columns[p]]
            if cell == "":
                continue
            conversion = settings.convert.get(p)
            if conversion is None:
                props[p] = cell
                continue
            converted = conversion.read(p, cell)
            if converted is None:
                props[conversion.fallback(p)] = cell
                unconverted[p].append(n)
            else:
                props.update(converted)
        nodes.append(
            Node(
                id=node_id,
                type=settings.type,
                key=key,
                label=_cell(cells, columns, settings.label),
                summary=_cell(cells, columns, settings.summary),
                props=_json(props) if props else None,
            )
        )
        evidence.append(
            Evidence(
                subject=node_id,
                source=name,
                locator=f"file={name};row={n}",
                method="extracted",
                producer=PRODUCER,
            )
        )

    made = Content(
        header=Header(kind="tessera", producer=PRODUCER, settings=settings.as_json()),
        sources=[
            Source(id=name, kind="file", hash=hashlib.sha256(data).hexdigest(), path=name),
        ],
        types=[
            Type(
                name=settings.type,
                kind="node",
                key_prop=settings.key,
                props=_json(prop_kinds(settings.props, settings.convert)),
            )
        ],
        nodes=nodes,
        evidence=evidence,
    )
    report = Report(
        {c: tuple(unconverted[c]) for c in sorted(unconverted, key=lambda c: c.encode("utf-8"))}
    )
    return made, report


def _check_settings(settings: Settings) -> None:
    if NODE_TYPE.fullmatch(settings.type) is None:
        raise ValueError(
            f"settings: type {settings.type!r} is not a node type name ^[A-Z][A-Za-z0-9]*$ (3.4)"
        )
    if len(settings.delimiter) != 1 or settings.delimiter in '"\r\n':
        raise ValueError(
            f"settings: delimiter {settings.delimiter!r} must be one character, "
            f"not a quote or line break"
        )
    try:
        codecs.lookup(settings.encoding)
    except LookupError:
        raise ValueError(f"settings: encoding {settings.encoding!r} is unknown") from None
    duplicates = sorted({p for p in settings.props if settings.props.count(p) > 1})
    if duplicates:
        raise ValueError(f"settings: props name {duplicates[0]!r} twice")
    check_conversions(settings.props, settings.convert)


def _decode(name: str, data: bytes, encoding: str) -> str:
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as e:
        raise ValueError(
            f"{name}: is not {encoding} text (at byte offset {e.start}: {e.reason})"
        ) from None
    return text.removeprefix("﻿")


def _parse(name: str, text: str, delimiter: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """The header row and the data rows, each with the line it starts on; blank lines dropped."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    records: list[tuple[int, list[str]]] = []
    try:
        line = reader.line_num + 1
        for record in reader:
            if record:
                records.append((line, record))
            line = reader.line_num + 1
    except csv.Error as e:
        raise ValueError(f"{name}: line {reader.line_num}: {e}") from None
    if not records:
        raise ValueError(f"{name}: has no header row")
    return records[0][1], records[1:]


def _columns(name: str, header: Sequence[str], settings: Settings) -> dict[str, int]:
    """The position of every column a setting names; refused when absent or ambiguous."""
    wanted = [c for c in (settings.key, settings.label, settings.summary) if c is not None]
    positions: dict[str, int] = {}
    for column in [*wanted, *settings.props]:
        found = [i for i, h in enumerate(header) if h == column]
        if not found:
            raise ValueError(f"{name}: column {column!r} is not in the header")
        if len(found) > 1:
            raise ValueError(f"{name}: column {column!r} appears twice in the header")
        positions[column] = found[0]
    return positions


def _cell(cells: Sequence[str], columns: Mapping[str, int], column: str | None) -> str | None:
    if column is None:
        return None
    value = cells[columns[column]]
    return value or None


def _json(value: Mapping[str, object]) -> str:
    """Canonical JSON text (RFC 8785, section 3.1) of an object of JSON values."""
    return canonical_json(json.dumps(value, ensure_ascii=False, allow_nan=False))
