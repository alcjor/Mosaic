"""Artifact models: what renderers produce and serializers write."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from mosaic_mock.engine.text import Piece, Ref, Text, plain, refs


@dataclass
class Scope:
    """A named range of lines, e.g. ``step=2`` or ``function=pwr_tc_dispatch``."""

    name: str
    first: int  # 0-based line index, inclusive
    last: int  # inclusive


@dataclass
class LinesFile:
    """Code, scripts and other line-oriented text. Locators are ``line=<n>``."""

    path: str
    lines: list[Text] = field(default_factory=list)
    scopes: list[Scope] = field(default_factory=list)

    def add(self, *pieces: Piece) -> int:
        self.lines.append(list(pieces))
        return len(self.lines) - 1

    def scope_of(self, idx: int) -> str:
        best: Scope | None = None
        for s in self.scopes:
            if s.first <= idx <= s.last and (
                best is None or s.last - s.first < best.last - best.first
            ):
                best = s
        return best.name if best else "file"

    def placements(self) -> Iterator[tuple[str, str, Ref]]:
        """(loc, scope, ref) for every reference."""
        for i, line in enumerate(self.lines):
            for r in refs(line):
                yield f"line={i + 1}", self.scope_of(i), r


@dataclass
class Para:
    text: Sequence[Piece]
    style: str = "body"  # body | bullet | caption | meta


@dataclass
class Table:
    header: list[str]
    rows: Sequence[Sequence[Sequence[Piece]]]
    caption: str | None = None


Block = Para | Table


@dataclass
class Section:
    number: str
    title: Sequence[Piece]
    level: int
    blocks: Sequence[Block] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)

    def walk(self) -> Iterator[Section]:
        yield self
        for c in self.children:
            yield from c.walk()

    def heading(self) -> str:
        return f"{self.number} {plain(self.title)}" if self.number else plain(self.title)


@dataclass
class Document:
    """A structured document written to one or more formats (html, docx, pdf).

    Locators are ``section=<number>`` of the innermost numbered section.
    """

    path: str  # without extension, e.g. "sum/sum"
    formats: tuple[str, ...]
    title: str
    front: list[Para] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    def walk(self) -> Iterator[Section]:
        for s in self.sections:
            yield from s.walk()

    def placements(self) -> Iterator[tuple[str, str, Ref]]:
        for sec in self.walk():
            loc = f"section={sec.number}"
            for r in refs(sec.title):
                yield loc, loc, r
            for b in sec.blocks:
                texts = [b.text] if isinstance(b, Para) else [c for row in b.rows for c in row]
                for t in texts:
                    for r in refs(t):
                        yield loc, loc, r


@dataclass
class TableFile:
    """A delimited record file. Locators are ``table=<TABLE>,row=<n>``."""

    path: str
    table: str
    rows: list[list[str]] = field(default_factory=list)
    delimiter: str = "\t"
    header: list[str] | None = None


@dataclass
class RawFile:
    path: str
    data: bytes


Artifact = LinesFile | Document | TableFile | RawFile
