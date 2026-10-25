"""The mocker's own minimal readers (MOCK-12): check that every ground-truth surface occurs
at its locator in the written files. Independent of the Mosaic extractors (MOCK-01)."""

from __future__ import annotations

import re
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

NUMBER = re.compile(r"^((?:\d+|[A-Z])(?:\.\d+)*)\s")


class _HtmlSections(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sections: dict[str, list[str]] = {}
        self.current = ""
        self._heading: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("h2", "h3", "h4", "h5", "h6"):
            self._heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip -= 1
        elif tag in ("h2", "h3", "h4", "h5", "h6") and self._heading is not None:
            text = "".join(self._heading)
            m = NUMBER.match(text)
            self.current = m.group(1) if m else self.current
            self.sections.setdefault(self.current, []).append(text)
            self._heading = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._heading is not None:
            self._heading.append(data)
        else:
            self.sections.setdefault(self.current, []).append(data)


def _docx_sections(path: Path) -> dict[str, str]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    out: dict[str, list[str]] = {}
    current = ""
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            if p.style is not None and (p.style.name or "").startswith("Heading"):
                m = NUMBER.match(p.text)
                current = m.group(1) if m else current
            out.setdefault(current, []).append(p.text)
        elif tag == "tbl":
            t = Table(child, doc)
            out.setdefault(current, []).extend(c.text for row in t.rows for c in row.cells)
    return {k: "\n".join(v) for k, v in out.items()}


@cache
def _read(path: Path) -> Any:
    if path.suffix == ".docx":
        return _docx_sections(path)
    if path.suffix in (".html", ".htm"):
        parser = _HtmlSections()
        parser.feed(path.read_text(encoding="utf-8"))
        return {k: " ".join(v) for k, v in parser.sections.items()}
    return path.read_text(encoding="utf-8").split("\n")


def text_at(root: Path, file: str, loc: str) -> str:
    """The text a locator points at, or ``""`` if it does not exist."""
    data = _read(root / file)
    key, _, value = loc.partition("=")
    if key == "line":
        n = int(value)
        return data[n - 1] if 0 < n <= len(data) else ""
    if key == "section":
        return data.get(value, "")
    if key == "table":
        row = int(loc.rsplit("row=", 1)[1])
        return data[row - 1] if 0 < row <= len(data) else ""
    raise ValueError(f"unknown locator {loc!r}")


def self_check(root: Path, truth: dict[str, Any]) -> list[str]:
    """Every mention's surface occurs at its locator (MOCK-12); returns the problems."""
    _read.cache_clear()
    problems = []
    for m in truth["mentions"]:
        if m["surface"] not in text_at(root, m["file"], m["loc"]):
            problems.append(f"{m['file']} {m['loc']}: {m['surface']!r} not found")
    for d in truth["defects"]:
        if d["mutated"] and d["mutated"] not in text_at(root, d["file"], d["loc"]):
            problems.append(f"defect {d['id']}: {d['mutated']!r} not at {d['file']} {d['loc']}")
    return problems
