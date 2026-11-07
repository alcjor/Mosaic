"""The mosaic an export carries when its view file names ``export.types`` (plan M3.10).

Answered on #140: the cut is a build (section 7.1). Its one piece is the source mosaic, of kind
``mosaic`` and pinned by its knowledge hash (section 5.1); its one target, ``export``, has the
view file's ``export.types`` as ``types`` (section 5.4: node types in scope, edges kept when both
ends are). So the cut's ``source`` holds the source mosaic's row, its evidence names the copied
rows with the source's hash at the end of ``via`` (sections 3.2 and 3.5), and its header's
``pattern_hash`` is the hash of the pattern written here. Each carried type keeps its key, its
declared properties, its description and its keys as they are (``normalise: []``); each carried
edge type keeps its description. The target keeps every fact (``trust: all``, ``evidence: all``)
and the source's ``text`` setting; it has vectors when the export carries the model. The pattern
is canonical JSON text, so the same mosaic and types give the same cut (principle 5).

The source is only read: it is opened by the reading rules and given to the builder as an
available piece file.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mosaic_format.reader import open as open_sealed

from mosaic_build.mosaic.build import build
from mosaic_build.mosaic.errors import BuildError

TARGET = "export"
"""The cut's target name; its header's ``target``."""

_PIECE = re.compile(r"[^A-Za-z0-9_-]+")
_TEXT = ("none", "snippets", "full")


class CutError(ValueError):
    """The cut cannot be built; the message names what failed."""


@dataclass(frozen=True)
class Source:
    """What a cut needs to know of its source mosaic."""

    knowledge_hash: str
    node_types: dict[str, tuple[str | None, list[str], str | None]]
    """Each node type: its key property, its declared properties and its description."""
    edge_types: list[tuple[str, str | None, str | None, str | None]]
    """Each edge type: its name, from, to and description, by name."""
    text: str


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def read_source(path: Path) -> Source:
    """The source mosaic's knowledge hash, declared types and ``text`` setting."""
    with open_sealed(path) as sealed:
        nodes: dict[str, tuple[str | None, list[str], str | None]] = {}
        for name, key, props, describe in sealed.query(
            "SELECT name, key_prop, props, description FROM type WHERE kind = 'node' "
            "ORDER BY name COLLATE BINARY"
        ):
            declared = json.loads(props) if isinstance(props, str) else {}
            nodes[str(name)] = (_text(key), [str(p) for p in declared], _text(describe))
        edges = [
            (str(n), _text(f), _text(t), _text(d))
            for n, f, t, d in sealed.query(
                "SELECT name, from_type, to_type, description FROM type WHERE kind = 'edge' "
                "ORDER BY name COLLATE BINARY"
            )
        ]
        rows = sealed.query("SELECT settings FROM header")
        knowledge_hash = sealed.knowledge_hash
    try:
        settings = json.loads(str(rows[0][0])) if rows else {}
    except ValueError:
        settings = {}
    text = settings.get("text") if isinstance(settings, dict) else None
    return Source(knowledge_hash, nodes, edges, text if text in _TEXT else "snippets")


def piece_name(source: Path) -> str:
    """The cut's name for its piece: the source file's name without its suffix (section 5.1)."""
    name = _PIECE.sub("-", Path(source.name).stem).lstrip("-_")
    return name or "source"


def pattern(source: Source, name: str, types: Sequence[str], vectors: bool) -> str:
    """The pattern the cut is built with, as canonical JSON text (YAML 1.2 reads it)."""
    node_types: dict[str, object] = {}
    for t in types:
        key, props, describe = source.node_types[t]
        if key is None:
            raise CutError(f"node type {t} has no key property, so it cannot be cut (section 3.9)")
        fields = {key: "key", **{p: p for p in props if p != key}}
        entry: dict[str, object] = {"key": key, "normalise": [], "from": {f"{name}.{t}": fields}}
        if describe:
            entry["describe"] = describe
        node_types[t] = entry
    edges: dict[str, object] = {}
    for edge, start, end, describe in source.edge_types:
        if start in types and end in types:
            entry = {"from": start, "to": end, "map": [f"{name}.{edge}"]}
            if describe:
                entry["describe"] = describe
            edges[edge] = entry
    document: dict[str, object] = {
        "format": "0.1",
        "pieces": [{"name": name, "hash": source.knowledge_hash, "kind": "mosaic"}],
        "types": node_types,
        "mosaics": {
            TARGET: {
                "types": list(types),
                "trust": "all",
                "evidence": "all",
                "text": source.text,
                "vectors": vectors,
            }
        },
    }
    if edges:
        document["edges"] = edges
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def cut(source_path: Path, types: Sequence[str], model: Path | None = None) -> bytes:
    """The bytes of the mosaic cut from ``source_path`` to ``types``; vectors with ``model``."""
    source = read_source(source_path)
    with tempfile.TemporaryDirectory(prefix="mosaic-cut-") as work:
        directory = Path(work)
        pattern_path = directory / "pattern.yaml"
        text = pattern(source, piece_name(source_path), types, model is not None)
        pattern_path.write_text(text, encoding="utf-8")
        out = directory / "out" / "cut.mosaic"
        try:
            build(pattern_path, TARGET, out, pieces=[source_path], model=model)
        except BuildError as e:
            raise CutError(f"the export's cut of {source_path} failed: {e}") from None
        return out.read_bytes()
