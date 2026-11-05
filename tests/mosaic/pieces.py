"""Seal small invented pieces for the mosaic builder's tests, and write patterns beside them."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mosaic_format import seal
from mosaic_format.writer import (
    Alias,
    Content,
    Evidence,
    ExternalRef,
    Header,
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
) -> str:
    """Seal a tessera of ``nodes`` and return its knowledge hash.

    Without ``evidence``, each node gets one row about the whole node at ``row=<n>``.
    """
    types = sorted({n.type for n in nodes})
    if evidence is None:
        evidence = [
            Evidence(
                subject=n.id,
                source=source,
                locator=f"file={source};row={i + 1}",
                method="extracted",
                producer=PRODUCER,
            )
            for i, n in enumerate(nodes)
        ]
    content = Content(
        header=Header(kind="tessera", producer=PRODUCER),
        sources=[
            Source(id=source, kind="file", hash=source_hash, path=source, notice=notice, text=text)
        ],
        types=[Type(name=t, kind="node") for t in types],
        nodes=nodes,
        aliases=aliases,
        evidence=evidence,
        external_refs=external_refs,
    )
    return seal(path, content).knowledge_hash


def evidence(
    subject: str,
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
    directory: Path, pieces: Sequence[str | Mapping[str, str]], types: Mapping[str, Any]
) -> Path:
    """Write ``pattern.yaml`` (JSON is YAML) with ``pieces`` and ``types``; return its path."""
    path = directory / "pattern.yaml"
    data = {"format": "0.1", "pieces": list(pieces), "types": types}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
