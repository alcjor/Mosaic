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


# --- what must match: reading 3, the maintainer's answer on #133 -------------------------------
#
# Equal: data values, `total`, the error codes the spec names for a case (`unknown_id`, section
# 8.1; `unknown_column`, section 8.6), tier and `table` order, `cite` rows in evidence order.
# Not compared exactly: `error.message` (not at all); suggestions (node ids, at most 5, with the
# expected first one); lists whose order the spec does not fix (`neighbors` edges; `get` links,
# aliases and external references), as sets; a case the spec names no code for, any code of the
# schema's list.


def _case(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The one-case file and a copy of its answer, to change."""
    return {name: CASES[name]}, {name: copy.deepcopy(CASES[name]["answer"])}


def test_an_error_message_is_not_compared() -> None:
    cases, answers = _case("get-unknown")
    answers["get-unknown"]["error"]["message"] = "unknown id Artist:Queen"
    assert differences(cases, answers) == []


def test_suggestions_may_be_fewer_if_they_keep_the_expected_first_one() -> None:
    cases, answers = _case("get-unknown")
    answers["get-unknown"]["error"]["suggestions"] = ["Artist:51"]
    assert differences(cases, answers) == []
    answers["get-unknown"]["error"]["suggestions"] = ["Track:1157", "Artist:51", "Album:1"]
    assert differences(cases, answers) == []


@pytest.mark.parametrize(
    "suggestions",
    [
        [],
        ["Track:1157"],
        ["Artist:51", "Album:1", "Album:2", "Album:3", "Album:4", "Album:5"],
        ["Artist:51", "not an id"],
        ["Artist:51", "Artist:99999"],
    ],
)
def test_suggestions_without_the_first_too_many_or_not_node_ids_differ(
    suggestions: list[str],
) -> None:
    cases, answers = _case("get-unknown")
    answers["get-unknown"]["error"]["suggestions"] = suggestions
    node_ids = {"Artist:51", "Track:1157", "Album:1", "Album:2", "Album:3", "Album:4", "Album:5"}
    assert differences(cases, answers, node_ids=node_ids)


def test_without_the_mosaic_suggestions_are_checked_as_ids() -> None:
    cases, answers = _case("get-unknown")
    answers["get-unknown"]["error"]["suggestions"] = ["Artist:51", "Artist:99999"]
    assert differences(cases, answers) == []
    answers["get-unknown"]["error"]["suggestions"] = ["Artist:51", "no colon"]
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ["get-unknown", "neighbors-unknown-id", "table-unknown-column"])
def test_a_code_the_spec_names_must_be_equal(name: str) -> None:
    cases, answers = _case(name)
    answers[name]["error"]["code"] = "bad_argument"
    assert differences(cases, answers)


@pytest.mark.parametrize(
    "name", ["cite-edge-unknown", "neighbors-unknown-edge", "find-unknown-type", "table-bad-op"]
)
def test_a_case_the_spec_names_no_code_for_takes_any_code_of_the_schema(name: str) -> None:
    cases, answers = _case(name)
    answers[name]["error"]["code"] = "bad_argument"
    assert differences(cases, answers) == []
    answers[name]["error"]["code"] = "not_a_code"
    assert differences(cases, answers)


def test_an_error_where_an_answer_is_expected_differs_and_so_does_the_reverse() -> None:
    cases, answers = _case("get-track")
    error = {"code": "unknown_id", "message": "", "suggestions": []}
    answers["get-track"] = {"tool": "get", "mosaic": answers["get-track"]["mosaic"], "error": error}
    assert differences(cases, answers)
    cases, answers = _case("get-unknown")
    answers["get-unknown"] = copy.deepcopy(CASES["get-track"]["answer"])
    assert differences(cases, answers)


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("neighbors-both", ("data", "edges")),
        ("get-track", ("data", "links")),
    ],
)
def test_lists_the_spec_does_not_order_are_compared_as_sets(
    name: str, path: tuple[str, str]
) -> None:
    cases, answers = _case(name)
    listed = answers[name][path[0]][path[1]]
    assert len(listed) > 1
    listed.reverse()
    assert differences(cases, answers) == []
    listed.pop()
    assert differences(cases, answers)


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("find-text", ("data", "results")),
        ("table-order-missing-last", ("data", "rows")),
        ("table-page-2", ("data", "rows")),
    ],
)
def test_lists_the_spec_orders_must_keep_their_order(name: str, path: tuple[str, str]) -> None:
    cases, answers = _case(name)
    answers[name][path[0]][path[1]].reverse()
    assert differences(cases, answers)


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("find-text", lambda a: a["data"].__setitem__("total", 9)),
        ("get-track", lambda a: a["data"]["props"].__setitem__("bytes", 1)),
        ("get-long-name", lambda a: a["data"].__setitem__("label", a["data"]["label"][:-1])),
        ("cite-edge", lambda a: a["data"]["evidence"][0].__setitem__("locator", "x")),
        ("table-page-2", lambda a: a["data"].__setitem__("page", 1)),
        ("neighbors-both", lambda a: a["data"]["edges"][0].__setitem__("label", "Other")),
        ("find-vector", lambda a: a.__setitem__("mosaic", "f" * 64)),
    ],
)
def test_data_values_must_be_equal(name: str, change: Any) -> None:
    cases, answers = _case(name)
    change(answers[name])
    assert differences(cases, answers)
