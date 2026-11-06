"""The build report (Specification 0.1, sections 7.2 and 7.3; decisions Q1-Q6 on #17).

Every build writes ``build-report.json`` in the directory of the mosaic file, also when it
fails. It is valid against ``spec/build-report.schema.json``:

- **Counts**: every node type in scope and every declared edge type (section 7.1 step 7), 0 when
  it has no rows (Q6), by type name in UTF-8 bytes.
- **Conflicts** on nodes, by node and property, then on edges, by from, type, to, qualifier and
  property; label and summary clashes only when the target is strict (section 7.3). A value is
  the JSON value itself.
- **Alias conflicts**, by node and winning spelling.
- **Stale references** and **mentions**, by piece and locator: only of rules whose edge type the
  target declares, and not of mentions whose containing node step 6 drops (Q5).
- **Weak ids**, by type: the mosaic's nodes, after step 6, that a weak-keyed piece node maps to;
  a type with none is not listed (Q1).
- **Proposals**: the outdated ones in file order, then those that no longer apply, in file
  order (Q3).
- **Notices**: one entry per distinct piece name in ``pieces`` and notice text, whatever the
  target, by piece and then text (Q3, Q4).

A failed build's report (Q2): when the build stops before step 6 (step 1, or invalid input met
while mapping, merging or linking), the hashes and ``file_size`` are null, ``counts`` is empty and
every list is empty; ``pattern_hash`` is the SHA-256 of the pattern file's bytes when it could be
read. A ``strict`` failure has the lists and ``counts`` but null hashes and size, since nothing
was sealed; an ``over_budget`` one has the removed file's hashes and size as well.

The bytes are a builder convention, not a spec rule (the report is not hashed): UTF-8 JSON with
keys in the schema's order, 2-space indent, non-ASCII characters as they are, LF line endings
and a final newline. The same build gives the same bytes.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mosaic_format.writer import Type

from mosaic_build.mosaic.link import PROPOSALS
from mosaic_build.mosaic.merge import Assembly, Given
from mosaic_build.mosaic.pieces import Inputs
from mosaic_build.mosaic.target import Target

REPORT = "build-report.json"
"""The report's file name, in the directory of the mosaic file (section 7.2)."""

FORMAT = "0.1"

TEXT_COLUMNS = ("label", "summary")
"""Properties whose clashes are reported only for a strict target (section 7.3)."""

type Report = dict[str, Any]


def _utf8(text: str) -> bytes:
    return text.encode("utf-8")


def _given(g: Given) -> dict[str, Any]:
    return {"value": g.value, "piece": g.piece}


def _empty() -> Report:
    return {"nodes": {}, "edges": {}}


def report(
    *,
    target: str,
    pattern_hash: str | None,
    reason: str | None = None,
    knowledge_hash: str | None = None,
    vector_hash: str | None = None,
    file_size: int | None = None,
    content: Report | None = None,
) -> Report:
    """A whole report, keys in the schema's order; ``content`` from :func:`content` or empty."""
    lists: Report = content or {
        "counts": _empty(),
        "conflicts": [],
        "alias_conflicts": [],
        "stale_references": [],
        "mentions": [],
        "weak_ids": [],
        "proposals": [],
        "notices": [],
    }
    return {
        "format": FORMAT,
        "outcome": "built" if reason is None else "failed",
        "reason": reason,
        "target": target,
        "pattern_hash": pattern_hash,
        "knowledge_hash": knowledge_hash,
        "vector_hash": vector_hash,
        "file_size": file_size,
        **lists,
    }


def content(inputs: Inputs, a: Assembly, t: Target, types: Sequence[Type]) -> Report:
    """Counts and lists of the selected content (after steps 6 and 7), in the schema's order."""
    return {
        "counts": _counts(a, types),
        "conflicts": _conflicts(a, t),
        "alias_conflicts": [
            {
                "node": c.node,
                "winner": _given(c.winner),
                "losers": [_given(g) for g in c.losers],
            }
            for c in a.alias_conflicts()
        ],
        "stale_references": [
            {"name": s.name, "type": s.type, "piece": s.piece, "locator": s.locator}
            for s in a.stale_references
        ],
        "mentions": [
            {
                "status": m.status,
                "role": m.role,
                "text": m.text,
                "piece": m.piece,
                "locator": m.locator,
                "candidates": list(m.candidates),
            }
            for m in a.mentions
        ],
        "weak_ids": _weak_ids(a),
        "proposals": _proposals(inputs, a),
        "notices": _notices(inputs, a),
    }


def _counts(a: Assembly, types: Sequence[Type]) -> Report:
    nodes = {t.name: 0 for t in sorted(types, key=lambda t: _utf8(t.name)) if t.kind == "node"}
    edges = {t.name: 0 for t in sorted(types, key=lambda t: _utf8(t.name)) if t.kind == "edge"}
    for n in a.nodes.values():
        nodes[n.type] += 1
    for k in a.edges:
        edges[k.type] += 1
    return {"nodes": nodes, "edges": edges}


def _conflicts(a: Assembly, t: Target) -> list[Report]:
    found: list[Report] = [
        {
            "node": c.node,
            "property": c.property,
            "winner": _given(c.winner),
            "losers": [_given(g) for g in c.losers],
        }
        for c in a.conflicts()
        if t.strict or c.property not in TEXT_COLUMNS
    ]
    found.extend(
        {
            "edge": {
                "type": c.edge.type,
                "from": c.edge.src,
                "to": c.edge.dst,
                "qualifier": c.edge.qualifier,
            },
            "property": c.property,
            "winner": _given(c.winner),
            "losers": [_given(g) for g in c.losers],
        }
        for c in a.edge_conflicts()
    )
    return found


def _weak_ids(a: Assembly) -> list[Report]:
    counts: dict[str, int] = {}
    for n in a.nodes.values():
        if n.weak:
            counts[n.type] = counts.get(n.type, 0) + 1
    return [{"type": t, "count": counts[t]} for t in sorted(counts, key=_utf8)]


def _proposals(inputs: Inputs, a: Assembly) -> list[Report]:
    listed = [] if inputs.proposals is None else inputs.proposals["proposals"]
    order = {p["id"]: i for i, p in enumerate(listed)}
    outdated = [p for p in a.proposals if p.status == "outdated"]
    applies = sorted(
        (p for p in a.proposals if p.status == "no_longer_applies"), key=lambda p: order[p.id]
    )
    return [{"id": p.id, "status": p.status} for p in [*outdated, *applies]]


def _notices(inputs: Inputs, a: Assembly) -> list[Report]:
    names = {p.name for p in inputs.pieces}
    found: set[tuple[str, str]] = set()
    for s in a.sources:
        if s.notice is None or s.id == PROPOSALS:
            continue
        piece = s.id.split("/", 1)[0]
        if piece in names:
            found.add((piece, s.notice))
    ordered = sorted(found, key=lambda pt: (_utf8(pt[0]), _utf8(pt[1])))
    return [{"piece": piece, "text": text} for piece, text in ordered]


def strict_problems(r: Report) -> list[str]:
    """What fails a strict target (section 7.3): conflicts, alias conflicts, unmatched mentions."""
    unmatched = sum(1 for m in r["mentions"] if m["status"] == "unmatched")
    problems = []
    for count, what in (
        (len(r["conflicts"]), "conflict"),
        (len(r["alias_conflicts"]), "alias conflict"),
        (unmatched, "unmatched mention"),
    ):
        if count:
            problems.append(f"{count} {what}{'' if count == 1 else 's'}")
    return problems


def write(directory: Path, r: Report) -> Path:
    """Write ``r`` as ``build-report.json`` in ``directory``; return its path."""
    path = directory / REPORT
    text = json.dumps(r, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))
    return path
