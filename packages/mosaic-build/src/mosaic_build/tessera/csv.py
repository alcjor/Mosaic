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
  CSV cannot tell an empty value from a missing one. Declared props are all ``text``.
- **Reading.** The bytes are decoded with the given encoding (a leading byte order mark is
  dropped) and parsed with Python's ``csv`` module, strict quoting, ``"`` as the quote and
  doubled quotes as escapes. A quoted line break stays inside its cell; a blank line is no
  row. A row with a different number of fields than the header is refused.
- **JSON text** (``settings``, ``props``) has no whitespace and object keys sorted by their
  UTF-16 code units, the canonical form of RFC 8785 for objects of text.

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
from dataclasses import dataclass
from pathlib import Path

from mosaic_format.writer import Content, Evidence, Header, Node, Sealed, Source, Type, seal

from mosaic_build import __version__

PRODUCER = f"mosaic-csv/{__version__}"
"""Written as the header's ``producer`` and the producer of every evidence row."""

NODE_TYPE = re.compile(r"[A-Z][A-Za-z0-9]*")
"""Node type names (section 3.4)."""


@dataclass(frozen=True)
class Settings:
    """What shapes a CSV tessera; recorded in ``header.settings`` as given.

    ``key``, ``label`` and ``summary`` name a column or are None; ``props`` names the columns
    that become props. ``key = None`` keys rows by their position.
    """

    type: str = "Row"
    key: str | None = None
    label: str | None = None
    summary: str | None = None
    props: tuple[str, ...] = ()
    encoding: str = "utf-8"
    delimiter: str = ","

    def as_json(self) -> str:
        """The settings as canonical JSON text, for ``header.settings``."""
        return _json(
            {
                "type": self.type,
                "key": self.key,
                "label": self.label,
                "summary": self.summary,
                "props": list(self.props),
                "encoding": self.encoding,
                "delimiter": self.delimiter,
            }
        )


def build(
    source: str | os.PathLike[str], out: str | os.PathLike[str], settings: Settings
) -> Sealed:
    """Read the CSV file ``source`` and write its tessera to the new file ``out``.

    Raises ``ValueError`` naming the file and the row, line or column when the settings or the
    file cannot make a tessera; no file is left at ``out`` then. An existing ``out`` is never
    overwritten (``FileExistsError``).
    """
    return seal(out, content(source, settings))


def content(source: str | os.PathLike[str], settings: Settings) -> Content:
    """The tessera's content for the CSV file ``source``, ready to seal."""
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
        props = {p: cells[columns[p]] for p in settings.props if cells[columns[p]] != ""}
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

    return Content(
        header=Header(kind="tessera", producer=PRODUCER, settings=settings.as_json()),
        sources=[
            Source(id=name, kind="file", hash=hashlib.sha256(data).hexdigest(), path=name),
        ],
        types=[
            Type(
                name=settings.type,
                kind="node",
                key_prop=settings.key,
                props=_json(dict.fromkeys(settings.props, "text")),
            )
        ],
        nodes=nodes,
        evidence=evidence,
    )


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


def _utf16(key: str) -> bytes:
    return key.encode("utf-16-be", "surrogatepass")


def _json(value: Mapping[str, object]) -> str:
    """Canonical JSON text of an object whose values are text, None, lists of text or objects."""

    def order(v: object) -> object:
        if isinstance(v, Mapping):
            return {k: order(v[k]) for k in sorted(v, key=_utf16)}
        if isinstance(v, list):
            return [order(x) for x in v]
        return v

    return json.dumps(order(value), ensure_ascii=False, separators=(",", ":"))
