"""The documented pattern and proposals examples follow the section 5.6 rules decided on #10.

Only the rules that need the pattern and proposals alone are checked here; the checker (#10)
implements all of them. Each rule is also shown to catch a broken variant.
"""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

EXAMPLES = Path(__file__).parent / "examples"


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))


def _piece_names(pattern: dict[str, Any]) -> list[str]:
    return [p.split("@", 1)[0] if isinstance(p, str) else p["name"] for p in pattern["pieces"]]


def _pieces_named_like_targets(pattern: dict[str, Any]) -> list[str]:
    """No target lists its own output among the pieces: no piece is named like a target."""
    return sorted(set(_piece_names(pattern)) & set(pattern["mosaics"]))


def _node_type(node_id: str) -> str:
    return node_id.split(":", 1)[0] if ":" in node_id else ""


def _proposal_problems(pattern: dict[str, Any], proposals: dict[str, Any]) -> list[str]:
    """Proposal ids have declared node types; edge proposals match a declared edge; identity
    proposals merge only ids of their node's type (decision on #58)."""
    types = set(pattern["types"])
    problems = []
    for p in proposals["proposals"]:
        ids = [p["node"]] if p["kind"] == "identity" else [p["from"], p["to"]]
        problems += [
            f"{p['id']}: {i!r} has no declared type" for i in ids if _node_type(i) not in types
        ]
        if p["kind"] == "identity":
            node_type = _node_type(p["node"])
            problems += [
                f"{p['id']}: same_as id {name!r} is not a {node_type}"
                for name in p.get("same_as", [])
                if _node_type(name) in types and _node_type(name) != node_type
            ]
        if p["kind"] == "edge":
            edge = pattern.get("edges", {}).get(p["type"])
            if edge is None:
                problems.append(f"{p['id']}: edge {p['type']!r} is not declared")
            elif (_node_type(p["from"]), _node_type(p["to"])) != (edge["from"], edge["to"]):
                problems.append(f"{p['id']}: ends do not match edge {p['type']!r}")
    return problems


def test_no_piece_of_the_example_is_named_like_a_target() -> None:
    assert _pieces_named_like_targets(_load("pattern-plant.yaml")) == []


def test_a_piece_named_like_a_target_is_caught() -> None:
    pattern = _load("pattern-plant.yaml")
    pattern["pieces"].append("ops@0123456789abcdef")
    assert _pieces_named_like_targets(pattern) == ["ops"]


def test_example_proposals_refer_to_declared_types_and_edges() -> None:
    assert _proposal_problems(_load("pattern-plant.yaml"), _load("proposals.yaml")) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"node": "Valve:TEMP-3"}, "no declared type"),
        ({"from": "Sensor:TEMP-3"}, "ends do not match"),
        ({"type": "feeds"}, "is not declared"),
        ({"to": "TEMP-3"}, "no declared type"),
        ({"node": "Sensor:TEMP-3", "same_as": ["TMP3", "Step:FOP-1"]}, "is not a Sensor"),
    ],
)
def test_broken_proposals_are_caught(change: dict[str, str], problem: str) -> None:
    proposals = copy.deepcopy(_load("proposals.yaml"))
    kind = "identity" if "node" in change else "edge"
    target = next(p for p in proposals["proposals"] if p["kind"] == kind)
    target.update(change)
    problems = _proposal_problems(_load("pattern-plant.yaml"), proposals)
    assert any(problem in line for line in problems), problems
