"""Read patterns and proposals as YAML 1.2 core schema, rejecting duplicate keys (section 5).

The parser is ``ruamel.yaml``'s; the values are built here from its events, by the core
schema of YAML 1.2.2 (section 10.3) alone. So ``yes`` and ``on`` stay text, ``017`` is
seventeen, a date is text, ``<<`` is an ordinary key, and a tag outside the core schema is
refused. The result is JSON data, since the pattern and proposals schemas are JSON Schemas:
mapping keys must be text.
"""

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError
from ruamel.yaml.events import (
    AliasEvent,
    DocumentEndEvent,
    DocumentStartEvent,
    Event,
    MappingEndEvent,
    MappingStartEvent,
    ScalarEvent,
    SequenceEndEvent,
    SequenceStartEvent,
    StreamEndEvent,
    StreamStartEvent,
)

MAX_VALUES = 100_000
"""The most values a document may expand to, aliases counted at each use (section 10)."""

MAX_DEPTH = 64
"""The deepest a document may nest collections (section 10); the schemas need fewer than 10."""

MAX_DIGITS = 1000
"""The most characters a number may have; Python refuses longer decimal integers anyway."""

type Path = tuple[str | int, ...]
"""Where a value lies in the document: mapping keys and sequence indexes from the root."""

_CORE = "tag:yaml.org,2002:"
_NULL = re.compile(r"null|Null|NULL|~|")
_BOOL = {"true": True, "True": True, "TRUE": True, "false": False, "False": False, "FALSE": False}
_INT = re.compile(r"[-+]?[0-9]+")
_OCT = re.compile(r"0o[0-7]+")
_HEX = re.compile(r"0x[0-9a-fA-F]+")
_FLOAT = re.compile(r"[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?")
_INF = re.compile(r"[-+]?\.(inf|Inf|INF)")
_NAN = re.compile(r"\.(nan|NaN|NAN)")


class YamlError(ValueError):
    """Not YAML 1.2 core schema JSON data; ``rule`` is ``yaml`` or ``duplicate-key``."""

    def __init__(self, file: str, line: int | None, rule: str, message: str) -> None:
        self.file = file
        self.line = line
        self.rule = rule
        self.message = message
        where = file if line is None else f"{file}:{line}"
        super().__init__(f"{where}: {message}")


@dataclass(frozen=True)
class Document:
    """The data of one YAML file and the line (1-based) where each value starts."""

    data: Any
    lines: dict[Path, int] = field(default_factory=dict)

    def line(self, path: Path) -> int | None:
        """The line of ``path``, else of its nearest parent that has one."""
        for end in range(len(path), -1, -1):
            if path[:end] in self.lines:
                return self.lines[path[:end]]
        return None


class _TooLong(ValueError):
    """A number longer than :data:`MAX_DIGITS`."""


def _long(text: str) -> str:
    if len(text) > MAX_DIGITS:
        raise _TooLong(text[:20])
    return text


def _int(text: str) -> int | None:
    if _INT.fullmatch(text):
        _long(text)
        return int(text, 10)
    if _OCT.fullmatch(text):
        _long(text)
        return int(text[2:], 8)
    if _HEX.fullmatch(text):
        _long(text)
        return int(text[2:], 16)
    return None


def _float(text: str) -> float | None:
    if _FLOAT.fullmatch(text):
        return float(_long(text))
    if _INF.fullmatch(text):
        return -math.inf if text.startswith("-") else math.inf
    if _NAN.fullmatch(text):
        return math.nan
    return None


def _resolve(text: str) -> object:
    """A plain scalar without a tag, by the core schema's tag resolution."""
    if _NULL.fullmatch(text):
        return None
    if text in _BOOL:
        return _BOOL[text]
    number = _int(text)
    if number is not None:
        return number
    real = _float(text)
    return text if real is None else real


class _Built(NamedTuple):
    """A value, how many values it expands to, and how many collections deep it nests."""

    data: object
    size: int
    height: int


class _Builder:
    def __init__(self, file: str, events: Iterator[Event]) -> None:
        self.file = file
        self.events = events
        self.lines: dict[Path, int] = {}
        self.anchors: dict[str, _Built] = {}
        self.count = 0

    def fail(self, event: Event | None, message: str, rule: str = "yaml") -> YamlError:
        line = None if event is None or event.start_mark is None else event.start_mark.line + 1
        return YamlError(self.file, line, rule, message)

    def next(self) -> Event:
        return next(self.events)

    def grow(self, event: Event, size: int) -> None:
        self.count += size
        if self.count > MAX_VALUES:
            raise self.fail(event, f"document too large: more than {MAX_VALUES} values")

    def document(self) -> object:
        event = self.next()
        if not isinstance(event, StreamStartEvent):
            raise self.fail(event, "not a YAML stream")
        event = self.next()
        if isinstance(event, StreamEndEvent):
            return None
        data = self.one_document(event)
        event = self.next()
        if not isinstance(event, StreamEndEvent):
            raise self.fail(
                event, "more than one document; a pattern or proposals file is one document"
            )
        return data

    def one_document(self, start: Event) -> object:
        if not isinstance(start, DocumentStartEvent):
            raise self.fail(start, "not a YAML document")
        version = getattr(start, "version", None)
        if version is not None and tuple(version) != (1, 2):
            shown = ".".join(str(part) for part in version)
            raise self.fail(start, f"%YAML {shown}: the file is read as YAML 1.2 only")
        data = self.value(self.next(), ()).data
        end = self.next()
        if not isinstance(end, DocumentEndEvent):
            raise self.fail(end, "not a YAML document end")
        return data

    def value(self, event: Event, path: Path) -> _Built:
        """Build the value that starts at ``event``, at nesting level ``len(path)``."""
        self.lines.setdefault(path, event.start_mark.line + 1)
        if isinstance(event, AliasEvent):
            anchor = str(event.anchor)
            if anchor not in self.anchors:
                raise self.fail(event, f"YAML alias *{anchor} has no anchor")
            built = self.anchors[anchor]
            # An alias repeats a value built elsewhere: its nesting counts from here.
            self.deep(event, len(path) + built.height)
            self.grow(event, built.size)
            return built
        if isinstance(event, ScalarEvent):
            built = _Built(self.scalar(event), 1, 0)
            self.grow(event, 1)
        elif isinstance(event, SequenceStartEvent):
            self.collection_tag(event, "seq")
            self.deep(event, len(path) + 1)
            built = self.sequence(path)
        elif isinstance(event, MappingStartEvent):
            self.collection_tag(event, "map")
            self.deep(event, len(path) + 1)
            built = self.mapping(path)
        else:
            raise self.fail(event, "not a YAML value")
        if event.anchor is not None:
            self.anchors[str(event.anchor)] = built
        return built

    def deep(self, event: Event, levels: int) -> None:
        if levels > MAX_DEPTH:
            raise self.fail(event, f"nested more than {MAX_DEPTH} levels deep")

    def collection_tag(self, event: Event, kind: str) -> None:
        tag = getattr(event, "tag", None)
        if tag is not None and str(tag) not in ("!", _CORE + kind):
            raise self.fail(event, f"tag {tag} is not a tag of the YAML 1.2 core schema")

    def scalar(self, event: ScalarEvent) -> object:
        try:
            return self.resolve_scalar(event)
        except _TooLong:
            raise self.fail(event, f"a number of more than {MAX_DIGITS} characters") from None

    def resolve_scalar(self, event: ScalarEvent) -> object:
        text = str(event.value)
        tag = None if event.tag is None else str(event.tag)
        if tag is None:
            return _resolve(text) if event.style is None else text
        if tag in ("!", _CORE + "str"):
            return text
        if tag == _CORE + "null" and _NULL.fullmatch(text):
            return None
        if tag == _CORE + "bool" and text in _BOOL:
            return _BOOL[text]
        if tag == _CORE + "int" and (number := _int(text)) is not None:
            return number
        if tag == _CORE + "float":
            real = _float(text)
            if real is None and (number := _int(text)) is not None:
                real = float(number)
            if real is not None:
                return real
        short = tag.replace(_CORE, "!!")
        if tag.startswith(_CORE) and tag[len(_CORE) :] in ("null", "bool", "int", "float"):
            raise self.fail(event, f"{text!r} is not a value of {short}")
        raise self.fail(event, f"tag {short} is not a tag of the YAML 1.2 core schema")

    def sequence(self, path: Path) -> _Built:
        items: list[object] = []
        size, height = 1, 0
        while not isinstance(event := self.next(), SequenceEndEvent):
            item = self.value(event, (*path, len(items)))
            items.append(item.data)
            size += item.size
            height = max(height, item.height)
        return _Built(items, size, height + 1)

    def mapping(self, path: Path) -> _Built:
        out: dict[str, object] = {}
        size, height = 1, 0
        while not isinstance(event := self.next(), MappingEndEvent):
            if not isinstance(event, ScalarEvent):
                raise self.fail(event, "a mapping key must be text, not a collection")
            key = self.scalar(event)
            if event.anchor is not None:
                self.anchors[str(event.anchor)] = _Built(key, 1, 0)
            if not isinstance(key, str):
                raise self.fail(event, f"a mapping key must be text, not {key!r}; quote it")
            if key in out:
                raise self.fail(event, f"duplicate key {key!r}", rule="duplicate-key")
            self.lines[(*path, key)] = event.start_mark.line + 1
            value = self.value(self.next(), (*path, key))
            out[key] = value.data
            size += value.size
            height = max(height, value.height)
        return _Built(out, size, height + 1)


def load(text: str, file: str) -> Document:
    """Read ``text``, the contents of ``file``, as one YAML 1.2 core schema document.

    Raises :class:`YamlError` naming the file and line when the text is not YAML, holds a
    duplicate key, a tag outside the core schema, a key that is not text, or more than one
    document.
    """
    builder = _Builder(file, iter(YAML(typ="safe", pure=True).parse(text)))
    try:
        data = builder.document()
    except MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        line = None if mark is None else mark.line + 1
        problem = e.problem or e.context or "unreadable"
        raise YamlError(file, line, "yaml", f"not valid YAML: {problem}") from None
    except YAMLError as e:
        raise YamlError(file, None, "yaml", f"not valid YAML: {e}") from None
    return Document(data, builder.lines)
