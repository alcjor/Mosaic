"""The kit's tool cases on the Chinook mosaic, checked without a mosaic (plan M3.4).

Specification 0.1, section 11: "tool cases with expected answers, on the Chinook mosaic. A kit's
answers match and are valid against ``answers.schema.json``". The slow test
(``tests/fixtures/test_chinook_tools.py``) builds the mosaic and runs every case in the kit; these
fast tests check every case's arguments (section 8.1) and expected answer (section 8.2,
``spec/answers.schema.json``), that the cases cover each tool, each ``find`` tier and the errors,
and that a changed expected answer makes the slow test fail.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import REPO
from tests.fixtures import test_chinook_tools
from tests.fixtures.expected import load_expected
from tests.fixtures.tool_cases import FILE, SCHEMA, argument_problem, differences, load

DATA = load()
CASES: dict[str, Any] = DATA["cases"]
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
CHINOOK = REPO / "conformance" / "fixtures" / "chinook"


def test_the_file_names_the_fixture_and_its_target() -> None:
    assert set(DATA) == {"comment", "fixture", "target", "cases"}
    assert DATA["fixture"] == "chinook"
    assert DATA["target"] in load_expected(CHINOOK)
    assert CASES


@pytest.mark.parametrize("name", list(CASES))
def test_every_case_calls_a_tool_with_the_arguments_section_8_1_gives_it(name: str) -> None:
    case = CASES[name]
    assert set(case) == {"tool", "arguments", "answer"}
    assert argument_problem(case["tool"], case["arguments"]) is None


@pytest.mark.parametrize("name", list(CASES))
def test_every_expected_answer_is_valid_against_the_answers_schema(name: str) -> None:
    errors = [e.message for e in VALIDATOR.iter_errors(CASES[name]["answer"])]
    assert not errors, errors


@pytest.mark.parametrize("name", list(CASES))
def test_every_answer_is_from_its_tool_and_the_expected_mosaic(name: str) -> None:
    """Section 8.2: each answer names its tool and the knowledge hash of the mosaic it read."""
    case = CASES[name]
    expected = load_expected(CHINOOK)[DATA["target"]]
    assert case["answer"]["tool"] == case["tool"]
    assert case["answer"]["mosaic"] == expected.knowledge_hash


def test_the_cases_cover_every_tool_with_an_answer_and_an_error() -> None:
    for tool in ("find", "get", "neighbors", "table", "cite"):
        answers = [c["answer"] for c in CASES.values() if c["tool"] == tool]
        assert any("data" in a for a in answers), tool
        assert any("error" in a for a in answers), tool


def test_the_find_cases_cover_each_tier() -> None:
    """Section 8.5: exact, text and vector."""
    tiers = {
        r["match"]
        for c in CASES.values()
        if c["tool"] == "find" and "data" in c["answer"]
        for r in c["answer"]["data"]["results"]
    }
    assert tiers == {"exact", "text", "vector"}
    exact_by_key = [
        c
        for c in CASES.values()
        if c["tool"] == "find"
        and ":" not in c["arguments"]["query"]
        and any(r["match"] == "exact" for r in c["answer"].get("data", {}).get("results", []))
    ]
    assert exact_by_key, "an exact match by key, not only by id"


def test_the_cases_cover_the_errors_a_reader_can_cause() -> None:
    codes = {c["answer"]["error"]["code"] for c in CASES.values() if "error" in c["answer"]}
    assert {"unknown_id", "unknown_type", "unknown_edge", "unknown_column", "bad_argument"} <= codes


def test_an_unknown_id_names_the_closest_matches() -> None:
    """Section 8.1: an unknown id is an error naming the closest matches, never empty success."""
    unknown = [c["answer"] for c in CASES.values() if "error" in c["answer"]]
    unknown = [a for a in unknown if a["error"]["code"] == "unknown_id"]
    assert unknown
    assert any(a["error"]["suggestions"] for a in unknown)


@pytest.mark.parametrize(
    ("tool", "arguments", "problem"),
    [
        ("path", {"from": "A:1", "to": "B:2"}, "not a tool the cases use"),
        ("find", [], "not an object"),
        ("find", {}, "find takes"),
        ("get", {"id": "A:1", "limit": 2}, "get takes"),
        ("cite", {"from": "A:1", "type": "e"}, "cite takes"),
        ("cite", {"id": "A:1", "from": "A:1"}, "cite takes"),
    ],
)
def test_wrong_arguments_are_named(tool: str, arguments: object, problem: str) -> None:
    found = argument_problem(tool, arguments)
    assert found is not None and problem in found


# --- a changed expected answer makes the slow test fail ----------------------------------------


def _answers() -> dict[str, Any]:
    return {name: copy.deepcopy(c["answer"]) for name, c in CASES.items()}


def test_the_expected_answers_have_no_differences_from_themselves() -> None:
    assert differences(CASES, _answers()) == []


def test_the_slow_test_passes_on_the_expected_answers() -> None:
    test_chinook_tools.test_every_case_gives_its_expected_answer(_answers())


def test_the_slow_test_fails_when_an_answer_differs() -> None:
    answers = _answers()
    name = next(iter(answers))
    answers[name]["mosaic"] = "f" * 64
    with pytest.raises(AssertionError, match=name):
        test_chinook_tools.test_every_case_gives_its_expected_answer(answers)


def test_the_slow_test_fails_when_a_case_has_no_answer() -> None:
    answers = _answers()
    name = next(reversed(answers))
    del answers[name]
    with pytest.raises(AssertionError, match=f"{name}: no answer"):
        test_chinook_tools.test_every_case_gives_its_expected_answer(answers)


def test_the_slow_test_fails_when_the_expected_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = _answers()  # read before the change: what the kit answers
    data = load()
    name = "get-track"
    data["cases"][name]["answer"]["data"]["label"] = "Something else"
    changed = tmp_path / FILE.name
    changed.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(test_chinook_tools, "FILE", changed)
    with pytest.raises(AssertionError, match=name):
        test_chinook_tools.test_every_case_gives_its_expected_answer(answers)
