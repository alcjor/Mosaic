"""Seal the files a pattern case describes, and fill in their hashes.

A case in ``conformance/invalid/patterns/<rule>/`` holds ``pattern.yaml``, optionally
``proposals.yaml``, and optionally ``files.json``, which describes sealed files the checker
is given:

- ``pieces``: file name → description; these are the available piece files (section 5.1).
  When the key is absent, the checker is given no piece files.
- ``built_from``: one description; the mosaic the proposals were made from (section 5.6).

A description is ``{"kind": ..., "types": {name: "node" | [from, to]}, "nodes": [id, ...]}``.
A piece is named by its knowledge hash, which section 3.6 defines from the content, so
``{{hash:<file name>}}`` and ``{{hash:built_from}}`` in the YAML files stand for the full
knowledge hash of the sealed file.
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mosaic_format import seal
from mosaic_format.writer import Content, Evidence, Header, Node, Source, Type

from tests.conftest import REPO

PATTERN_CASES = REPO / "conformance" / "invalid" / "patterns"
PLACEHOLDER = re.compile(r"\{\{hash:([^}]+)\}\}")


def content(description: Mapping[str, Any]) -> Content:
    """The content of one described file: its types, and its nodes with one evidence row each."""
    kind = description["kind"]
    types = []
    for name, shape in sorted(description.get("types", {}).items()):
        if shape == "node":
            types.append(Type(name=name, kind="node"))
        else:
            types.append(Type(name=name, kind="edge", from_type=shape[0], to_type=shape[1]))
    nodes = [
        Node(id=i, type=i.split(":", 1)[0], key=i.split(":", 1)[1])
        for i in description.get("nodes", [])
    ]
    header = Header(kind=kind, producer="conformance/0.1")
    if kind == "mosaic":
        header = Header(kind=kind, producer="conformance/0.1", pattern_hash="0" * 64, target="t")
    source_kind = "tessera" if kind == "mosaic" else "file"
    source = Source(id="src", kind=source_kind, hash="0" * 64, path="src.txt")
    evidence = [
        Evidence(
            subject=n.id,
            source="src",
            locator=f"line={i + 1}",
            method="extracted",
            producer="conformance/0.1",
        )
        for i, n in enumerate(nodes)
    ]
    return Content(header=header, sources=[source], types=types, nodes=nodes, evidence=evidence)


def prepare(case: Path, out: Path) -> dict[str, Any]:
    """Seal the case's files into ``out`` and return the keyword arguments of ``check_pattern``."""
    described = (
        json.loads((case / "files.json").read_text("utf-8"))
        if (case / "files.json").is_file()
        else {}
    )
    hashes: dict[str, str] = {}
    kwargs: dict[str, Any] = {}
    if "pieces" in described:
        kwargs["pieces"] = []
        for name, description in sorted(described["pieces"].items()):
            path = out / name
            hashes[name] = seal(path, content(description)).knowledge_hash
            kwargs["pieces"].append(path)
    if "built_from" in described:
        path = out / "built_from.mosaic"
        hashes["built_from"] = seal(path, content(described["built_from"])).knowledge_hash
        kwargs["built_from"] = path

    def fill(name: str) -> Path:
        text = (case / name).read_text("utf-8")
        filled = PLACEHOLDER.sub(lambda m: hashes[m.group(1)], text)
        path = out / name
        path.write_text(filled, "utf-8", newline="\n")
        return path

    kwargs["pattern"] = fill("pattern.yaml")
    if (case / "proposals.yaml").is_file():
        kwargs["proposals"] = fill("proposals.yaml")
    return kwargs
