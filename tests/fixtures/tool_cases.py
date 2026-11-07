"""The kit's tool cases on the Chinook mosaic (Specification 0.1, sections 8 and 11; plan M3.4).

``conformance/tools/expected-answers.json`` holds the cases: each names a tool, its arguments and
the answer the kit must give on the Chinook mosaic that ``conformance/fixtures/chinook`` builds.
Its shape::

    {
      "comment": "...",
      "fixture": "chinook",
      "target": "default",
      "cases": {"<name>": {"tool": "<tool>", "arguments": {...}, "answer": {...}}, ...}
    }

The file is CODEOWNERS-protected: agents propose it, the maintainer merges it. The slow test
runs every case in the kit (``kit/scripts/run-cases.ts``) and compares through
:func:`differences`; the fast tests check every case's arguments and answer without a mosaic.
"""

import json
from pathlib import Path
from typing import Any

from tests.conftest import REPO

FILE = REPO / "conformance" / "tools" / "expected-answers.json"
SCHEMA = REPO / "spec" / "answers.schema.json"

ARGUMENTS: dict[str, tuple[frozenset[str], ...]] = {
    "find": (frozenset({"query", "type", "limit"}),),
    "get": (frozenset({"id"}),),
    "neighbors": (frozenset({"id", "edge", "direction", "limit"}),),
    "table": (frozenset({"type", "columns", "where", "order", "page"}),),
    "cite": (frozenset({"id"}), frozenset({"from", "type", "to", "qualifier"})),
}
"""Section 8.1: the arguments each tool the cases use takes (``cite`` a node or an edge)."""

REQUIRED: dict[str, tuple[frozenset[str], ...]] = {
    "find": (frozenset({"query"}),),
    "get": (frozenset({"id"}),),
    "neighbors": (frozenset({"id"}),),
    "table": (frozenset({"type"}),),
    "cite": (frozenset({"id"}), frozenset({"from", "type", "to"})),
}
"""Section 8.1: the arguments each tool needs, in the same order as :data:`ARGUMENTS`."""


def load(path: Path = FILE) -> dict[str, Any]:
    """The cases file, read as JSON with its cases in the file's order."""
    return json.loads(path.read_text(encoding="utf-8"))


def argument_problem(tool: str, arguments: object) -> str | None:
    """Why ``arguments`` are not a call of ``tool`` that section 8.1 describes, or None."""
    if tool not in ARGUMENTS:
        return f"{tool!r} is not a tool the cases use ({', '.join(ARGUMENTS)})"
    if not isinstance(arguments, dict):
        return "arguments are not an object"
    names = frozenset(arguments)
    for allowed, needed in zip(ARGUMENTS[tool], REQUIRED[tool], strict=True):
        if needed <= names <= allowed:
            return None
    shapes = " or ".join(str(sorted(a)) for a in ARGUMENTS[tool])
    return f"{tool} takes {shapes}, not {sorted(names)}"


def differences(cases: dict[str, Any], answers: dict[str, Any]) -> list[str]:
    """Each case whose answer differs from the expected one, or that has no answer."""
    found = []
    for name, case in cases.items():
        if name not in answers:
            found.append(f"{name}: no answer")
        elif answers[name] != case["answer"]:
            found.append(
                f"{name}: expected {json.dumps(case['answer'], ensure_ascii=False)[:300]}, "
                f"answered {json.dumps(answers[name], ensure_ascii=False)[:300]}"
            )
    found += [f"{name}: answered, but not a case" for name in answers if name not in cases]
    return found
