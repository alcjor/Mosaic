"""Ground-truth records and the ``ground_truth.json`` document (04-mocker § 3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class Placement:
    """One reference written somewhere: ``(file, locator, surface, item, role, match)``."""

    file: str
    loc: str
    scope: str  # the enclosing structural scope (step=2, section=4.2, function=f, file)
    surface: str
    item: str
    role: str
    match: str


@dataclass(frozen=True)
class XrefTruth:
    type: str
    from_file: str
    from_scope: str
    to_file: str
    to_scope: str

    def as_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "from": {"file": self.from_file, "scope": self.from_scope},
            "to": {"file": self.to_file, "scope": self.to_scope},
        }


@dataclass
class Defect:
    id: str
    kind: str
    file: str
    loc: str
    original: str
    mutated: str
    expected_detection: str
    extra: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "file": self.file,
            "loc": self.loc,
            "original": self.original,
            "mutated": self.mutated,
            "expected_detection": self.expected_detection,
        }
        d.update(self.extra)
        return d


def schema() -> dict[str, Any]:
    """The JSON Schema shipped with the mocker for ``ground_truth.json``."""
    text = resources.files("mosaic_mock").joinpath("ground_truth.schema.json").read_text()
    return json.loads(text)


def dumps(doc: dict[str, Any]) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode()
