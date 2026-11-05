"""Seal small invented pieces for the mosaic builder's tests, and write patterns beside them."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mosaic_format import seal
from mosaic_format.writer import (
    Alias,
    Content,
    Edge,
    EdgeKey,
    Evidence,
    ExternalRef,
    Header,
    Mention,
    Node,
    Source,
    Type,
)

PRODUCER = "test-builder/0.1"


def node(
    id_: str,
    key: str,
    label: str | None = None,
    summary: str | None = None,
    **props: Any,
) -> Node:
    """A piece node; its type is the part of ``id_`` before the first ``:``."""
    return Node(
        id=id_,
        type=id_.split(":", 1)[0],
        key=key,
        label=label,
        summary=summary,
        props=json.dumps(props) if props else None,
    )


def tessera(
    path: Path,
    nodes: Sequence[Node],
    *,
    source: str = "src.csv",
    source_hash: str = "a" * 64,
    notice: str | None = None,
    text: str | None = None,
    aliases: Sequence[Alias] = (),
    evidence: Sequence[Evidence] | None = None,
    external_refs: Sequence[ExternalRef] = (),
    edges: Sequence[Edge] = (),
    mentions: Sequence[Mention] = (),
    producer: str = PRODUCER,
    declared: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """Seal a tessera of ``nodes`` and ``edges`` and return its knowledge hash.

    ``declared`` gives a type's declared properties and their kinds (section 3.4); other types
    declare none.

    Without ``evidence``, each node gets one row about the whole node at ``row=<n>`` and each
    edge one at ``edge=<n>``. An edge type's ends are the types of its first edge's ends.
    """
    types = sorted({n.type for n in nodes})
    kinds = {n.id: n.type for n in nodes}
    edge_types: dict[str, tuple[str, str]] = {}
    for e in edges:
        edge_types.setdefault(e.type, (kinds[e.src], kinds[e.dst]))
    if evidence is None:
        evidence = [
            Evidence(
                subject=n.id,
                source=source,
                locator=f"file={source};row={i + 1}",
                method="extracted",
                producer=producer,
            )
            for i, n in enumerate(nodes)
        ] + [
            Evidence(
                subject=e.key,
                source=source,
                locator=f"file={source};edge={i + 1}",
                method="extracted",
                producer=producer,
            )
            for i, e in enumerate(edges)
        ]
    content = Content(
        header=Header(kind="tessera", producer=producer),
        sources=[
            Source(id=source, kind="file", hash=source_hash, path=source, notice=notice, text=text)
        ],
        types=[Type(name=t, kind="node", props=_declared(declared, t)) for t in types]
        + [
            Type(
                name=t,
                kind="edge",
                from_type=ends[0],
                to_type=ends[1],
                props=_declared(declared, t),
            )
            for t, ends in sorted(edge_types.items())
        ],
        nodes=nodes,
        edges=edges,
        aliases=aliases,
        evidence=evidence,
        mentions=mentions,
        external_refs=external_refs,
    )
    return seal(path, content).knowledge_hash


def _declared(declared: Mapping[str, Mapping[str, str]] | None, type_: str) -> str:
    return json.dumps(dict((declared or {}).get(type_, {})))


def evidence(
    subject: str | EdgeKey,
    locator: str,
    *,
    source: str = "src.csv",
    prop: str | None = None,
    snippet: str | None = None,
    method: str = "extracted",
    confidence: float | None = None,
    via: str | None = None,
) -> Evidence:
    return Evidence(
        subject=subject,
        source=source,
        locator=locator,
        method=method,
        producer=PRODUCER,
        prop=prop,
        confidence=confidence,
        via=via,
        snippet=snippet,
    )


def mosaic(
    path: Path,
    content: Content,
) -> str:
    """Seal a mosaic and return its knowledge hash."""
    return seal(path, content).knowledge_hash


def pattern(
    directory: Path,
    pieces: Sequence[str | Mapping[str, str]],
    types: Mapping[str, Any],
    edges: Mapping[str, Any] | None = None,
    mosaics: Mapping[str, Any] | None = None,
) -> Path:
    """Write ``pattern.yaml`` (JSON is YAML) with ``pieces``, ``types``, ``edges``, ``mosaics``."""
    path = directory / "pattern.yaml"
    data: dict[str, Any] = {"format": "0.1", "pieces": list(pieces), "types": types}
    if edges is not None:
        data["edges"] = edges
    if mosaics is not None:
        data["mosaics"] = mosaics
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def proposals(
    directory: Path, entries: Sequence[Mapping[str, Any]], built_from: str = "0" * 64
) -> Path:
    """Write ``proposals.yaml`` (JSON is YAML) with ``entries``; return its path."""
    path = directory / "proposals.yaml"
    data = {"format": "0.1", "built_from": built_from, "proposals": list(entries)}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def identity(
    id_: str, node: str, same_as: Sequence[str], decision: str = "accepted"
) -> dict[str, Any]:
    """An identity proposal by a person, decided by ``ana`` unless it is open."""
    p: dict[str, Any] = {
        "id": id_,
        "kind": "identity",
        "by": "ana",
        "evidence": [{"source": "notes", "locator": "line=1"}],
        "decision": decision,
        "node": node,
        "same_as": list(same_as),
    }
    if decision != "open":
        p["decided_by"] = "ana"
    return p


def edge_proposal(
    id_: str, type_: str, src: str, dst: str, decision: str = "accepted"
) -> dict[str, Any]:
    """An edge proposal by an assistant, decided by ``ana`` unless it is open."""
    p: dict[str, Any] = {
        "id": id_,
        "kind": "edge",
        "by": "helper/1.0",
        "confidence": 0.7,
        "evidence": [{"source": "notes", "locator": "line=2"}],
        "decision": decision,
        "type": type_,
        "from": src,
        "to": dst,
    }
    if decision != "open":
        p["decided_by"] = "ana"
    return p
