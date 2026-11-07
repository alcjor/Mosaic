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

The file is CODEOWNERS-protected: agents propose it, the maintainer merges it. It keeps this
kit's full answers as examples; what another kit's answer must match is :func:`differences`
(the maintainer's answer on #133, reading 3). The slow test runs every case in the kit
(``kit/scripts/run-cases.ts``) and compares through it; the fast tests check every case's
arguments and answer without a mosaic.
"""

import json
import re
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


SPEC_CODES = frozenset({"unknown_id", "unknown_column"})
"""The error codes the spec names for a case: an unknown id (section 8.1, with the code
``answers.schema.json`` gives it) and a column a type does not have (section 8.6). Any other
expected error takes any code of the schema's list."""

UNORDERED: dict[str, tuple[str, ...]] = {
    "neighbors": ("edges",),
    "get": ("links", "aliases", "external_refs"),
}
"""The lists of ``data`` whose order the spec does not fix, compared as sets (answer on #133)."""

NODE_ID = re.compile(r"[A-Z][A-Za-z0-9]*:.+", re.DOTALL)
"""A node id: a node type name (section 3.4), a colon and a key."""

SUGGESTION_LIMIT = 5
"""``answers.schema.json``: an error names at most 5 suggestions."""


def _codes() -> frozenset[str]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return frozenset(schema["$defs"]["error"]["properties"]["error"]["properties"]["code"]["enum"])


def _as_set(items: list[Any]) -> list[str]:
    return sorted(json.dumps(i, sort_keys=True, ensure_ascii=False) for i in items)


def _comparable(tool: str, answer: dict[str, Any]) -> dict[str, Any]:
    """``answer`` with the lists the spec does not order sorted, so they compare as sets."""
    if "data" not in answer:
        return answer
    data = dict(answer["data"])
    for key in UNORDERED.get(tool, ()):
        if isinstance(data.get(key), list):
            data[key] = _as_set(data[key])
    return {**answer, "data": data}


def _error_problems(
    expected: dict[str, Any], got: dict[str, Any], node_ids: frozenset[str] | set[str] | None
) -> list[str]:
    want, have = expected["error"], got["error"]
    if not isinstance(have, dict):
        return ["the error is not an object"]
    problems = []
    code = have.get("code")
    if want["code"] in SPEC_CODES:
        if code != want["code"]:
            problems.append(f"code {code!r}, expected {want['code']!r} (the spec names it)")
    elif not isinstance(code, str) or code not in _codes():
        problems.append(f"code {code!r} is not a code of answers.schema.json")
    suggestions = have.get("suggestions")
    if not isinstance(suggestions, list) or len(suggestions) > SUGGESTION_LIMIT:
        return [*problems, f"suggestions {suggestions!r}: a list of at most {SUGGESTION_LIMIT} ids"]
    for s in suggestions:
        if not isinstance(s, str) or NODE_ID.fullmatch(s) is None:
            problems.append(f"suggestion {s!r} is not a node id")
        elif node_ids is not None and s not in node_ids:
            problems.append(f"suggestion {s!r} is no node of the mosaic")
    if want["suggestions"] and want["suggestions"][0] not in suggestions:
        problems.append(
            f"suggestions {suggestions!r} leave out the best match {want['suggestions'][0]!r}"
        )
    return problems


def differences(
    cases: dict[str, Any],
    answers: dict[str, Any],
    *,
    node_ids: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Each case whose answer does not match the expected one, or that has no answer.

    What must match is the maintainer's answer on #133 (reading 3): the tool, the mosaic, the
    data values, ``total``, tier and ``table`` order and ``cite`` rows in evidence order are
    equal; the lists the spec does not order (:data:`UNORDERED`) are equal as sets. An expected
    error must be an error: its code equal when the spec names it (:data:`SPEC_CODES`), else any
    code of the schema's list; its message is not compared; its suggestions are node ids (of
    ``node_ids`` when given), at most 5, among them the expected first one, the best match.
    """
    found = []
    for name, case in cases.items():
        if name not in answers:
            found.append(f"{name}: no answer")
            continue
        want, got = case["answer"], answers[name]
        if (
            not isinstance(got, dict)
            or got.get("tool") != want["tool"]
            or got.get("mosaic") != want["mosaic"]
        ):
            found.append(
                f"{name}: tool or mosaic differs: {json.dumps(got, ensure_ascii=False)[:200]}"
            )
        elif ("error" in want) != ("error" in got):
            found.append(
                f"{name}: expected {'an error' if 'error' in want else 'an answer'}, got "
                f"{json.dumps(got, ensure_ascii=False)[:300]}"
            )
        elif "error" in want:
            found += [f"{name}: {p}" for p in _error_problems(want, got, node_ids)]
        elif not isinstance(got.get("data"), dict):
            found.append(
                f"{name}: data is not an object: {json.dumps(got, ensure_ascii=False)[:200]}"
            )
        elif _comparable(case["tool"], got) != _comparable(case["tool"], want):
            found.append(
                f"{name}: expected {json.dumps(want, ensure_ascii=False)[:300]}, "
                f"answered {json.dumps(got, ensure_ascii=False)[:300]}"
            )
    found += [f"{name}: answered, but not a case" for name in answers if name not in cases]
    return found
