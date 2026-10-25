"""Text with typed references.

Renderers build text as a list of pieces: plain strings, styled strings and `Ref`s. A
`Ref` is one reference to a world item. Defects mutate refs in place; the ground truth is
read off the final pieces, so it always matches what was written.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass
class Ref:
    item: str  # "TYPE/KEY"
    text: str
    role: str  # the pack's role for this spot (sends, reads, describes, mentions, …)
    match: str = "exact"  # exact | fuzzy_only | none (a defect removed it)
    form: str = "id"  # id | mn | ld | other: what kind of surface this is


@dataclass
class Styled:
    text: str
    mark: str  # b | i | code


Piece = str | Ref | Styled
Text = list[Piece]

TOKEN = re.compile(r"⟦([A-Za-z0-9_]+/[^:⟧]+):([a-z]+)⟧")


def plain(text: Iterable[Piece]) -> str:
    return "".join(p if isinstance(p, str) else p.text for p in text)


def refs(text: Iterable[Piece]) -> list[Ref]:
    return [p for p in text if isinstance(p, Ref)]


def tok(item: str, form: str) -> str:
    """A protected token, as passed through templates and the optional LLM (MOCK-21)."""
    return f"⟦{item}:{form}⟧"


def parse_tokens(s: str, resolve: Callable[[str, str], Ref]) -> Text:
    """Split template output into pieces, turning each token into a `Ref`."""
    out: Text = []
    pos = 0
    for m in TOKEN.finditer(s):
        if m.start() > pos:
            out.append(s[pos : m.start()])
        out.append(resolve(m.group(1), m.group(2)))
        pos = m.end()
    if pos < len(s):
        out.append(s[pos:])
    return out


def tokens_in(s: str) -> list[str]:
    return [m.group(0) for m in TOKEN.finditer(s)]
