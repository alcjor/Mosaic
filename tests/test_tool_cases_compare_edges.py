"""Edge cases of how a kit's answers are compared with the expected ones (plan M3.4; verifier).

The maintainer's answer on #133 (reading 3): data values, ``total``, tier and ``table`` order and
``cite`` rows in evidence order are equal; error messages are not compared; suggestions are node
ids, at most 5, with the expected first one; ``neighbors`` edges and ``get`` links, aliases and
external references are compared as sets; the codes ``unknown_id`` and ``unknown_column`` are equal
and any other expected error takes any code of ``spec/answers.schema.json``. Specification 0.1
sections 8.1, 8.2, 8.5, 8.6 and 11. Everything here runs on the expected answers or a copy changed
in one place; no mosaic is built.
"""

import copy
import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.fixtures.tool_cases import SCHEMA, differences, load

CASES: dict[str, Any] = load()["cases"]
SCHEMA_JSON = json.loads(SCHEMA.read_text(encoding="utf-8"))
CODES = SCHEMA_JSON["$defs"]["error"]["properties"]["error"]["properties"]["code"]["enum"]

VALIDATOR = Draft202012Validator(SCHEMA_JSON)
ERRORS = [n for n, c in CASES.items() if "error" in c["answer"]]
ANSWERS = [n for n, c in CASES.items() if "data" in c["answer"]]
UNORDERED = {"neighbors": ("edges",), "get": ("links", "aliases", "external_refs")}
ORDERED = ("results", "rows", "evidence", "columns")


def _rejected(cases: dict[str, Any], answers: dict[str, Any]) -> bool:
    """The slow test fails: the answer differs, or it is not valid against the schema."""
    return bool(differences(cases, answers)) or any(
        not VALIDATOR.is_valid(a) for a in answers.values()
    )


def _one(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return {name: CASES[name]}, {name: copy.deepcopy(CASES[name]["answer"])}


def _lists(name: str, keys: tuple[str, ...]) -> list[str]:
    data = CASES[name]["answer"].get("data", {})
    return [k for k in keys if isinstance(data.get(k), list) and len(data[k]) > 1]


# --- the answers that are not answers: a difference, never a crash ------------------------------

BROKEN: list[Any] = [None, [], "text", 7, {}, {"tool": "get"}, {"mosaic": "0" * 64}]


@pytest.mark.parametrize("name", list(CASES))
@pytest.mark.parametrize("broken", BROKEN, ids=lambda b: json.dumps(b))
def test_an_answer_that_is_no_answer_object_is_a_difference_not_a_crash(
    name: str, broken: Any
) -> None:
    # section 11: a kit's answers match; one that does not is reported, however it is wrong.
    cases, _ = _one(name)
    assert differences(cases, {name: broken})


@pytest.mark.parametrize("name", ANSWERS)
@pytest.mark.parametrize("data", [None, "text", 7, [], [1, 2]], ids=lambda b: json.dumps(b))
def test_data_that_is_no_object_is_a_difference_not_a_crash(name: str, data: Any) -> None:
    # section 8.2: `data` holds everything read from the file, an object per answers.schema.json.
    cases, answers = _one(name)
    answers[name]["data"] = data
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ANSWERS)
@pytest.mark.parametrize("value", [None, "x", 7, {"a": 1}], ids=lambda b: json.dumps(b))
def test_an_unordered_list_that_is_no_list_is_a_difference_not_a_crash(
    name: str, value: Any
) -> None:
    # section 8.1: `edges`, `links`, `aliases` and `external_refs` are lists.
    keys = UNORDERED.get(CASES[name]["tool"], ())
    if not keys:
        pytest.skip("this tool has no list the spec leaves unordered")
    cases, answers = _one(name)
    answers[name]["data"][keys[0]] = value
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ERRORS)
@pytest.mark.parametrize("error", [None, "unknown_id", [], 7, {}], ids=lambda b: json.dumps(b))
def test_an_error_that_is_no_error_object_or_lacks_its_fields_differs(
    name: str, error: Any
) -> None:
    # section 8.2 and answers.schema.json: an error has `code`, `message` and `suggestions`.
    cases, answers = _one(name)
    answers[name]["error"] = error
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ERRORS)
@pytest.mark.parametrize(
    "suggestions", [None, "Artist:51", {"Artist:51": 1}, [None], [51], [["Artist:51"]]]
)
def test_suggestions_that_are_no_list_of_strings_differ(name: str, suggestions: Any) -> None:
    # answers.schema.json: `suggestions` is an array of ids.
    cases, answers = _one(name)
    answers[name]["error"]["suggestions"] = suggestions
    assert differences(cases, answers)


# --- what is equal: every case ------------------------------------------------------------------


@pytest.mark.parametrize("name", list(CASES))
def test_a_case_answered_with_its_expected_answer_reordered_in_keys_only_matches(
    name: str,
) -> None:
    # JSON objects have no key order (section 3.1's canonical form is for stored text only).
    cases, answers = _one(name)
    answers[name] = json.loads(json.dumps(answers[name], sort_keys=True))
    assert differences(cases, answers) == []


@pytest.mark.parametrize("name", list(CASES))
def test_the_tool_and_the_mosaic_must_be_those_of_the_case(name: str) -> None:
    # section 8.2: every answer holds the tool name and the mosaic's knowledge hash.
    cases, answers = _one(name)
    other = next(
        t for t in ("find", "get", "neighbors", "table", "cite") if t != answers[name]["tool"]
    )
    answers[name]["tool"] = other
    assert differences(cases, answers)
    cases, answers = _one(name)
    answers[name]["mosaic"] = "0" * 64
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ANSWERS)
def test_an_answer_with_a_field_more_or_less_in_its_data_differs(name: str) -> None:
    # answers.schema.json: each tool's data has these fields and no others.
    cases, answers = _one(name)
    answers[name]["data"]["extra"] = 1
    assert differences(cases, answers)
    cases, answers = _one(name)
    del answers[name]["data"][next(iter(answers[name]["data"]))]
    assert differences(cases, answers)


@pytest.mark.parametrize("name", [n for n in ANSWERS if "total" in CASES[n]["answer"]["data"]])
def test_a_total_one_more_or_less_differs(name: str) -> None:
    # section 8.2: lists are cut with the total count, which is data.
    for delta in (1, -1):
        cases, answers = _one(name)
        answers[name]["data"]["total"] += delta
        assert differences(cases, answers)


@pytest.mark.parametrize("name", ANSWERS)
def test_a_number_is_not_its_text_and_a_null_is_not_a_missing_value(name: str) -> None:
    # section 8.6: values compare by kind; an answer with every number as text is not the answer.
    cases, answers = _one(name)

    def textual(v: Any) -> Any:
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return [textual(i) for i in v]
        if isinstance(v, dict):
            return {k: textual(i) for k, i in v.items()}
        return v

    changed = textual(answers[name]["data"])
    if changed == answers[name]["data"]:
        pytest.skip("this answer holds no number")
    answers[name]["data"] = changed
    assert differences(cases, answers)


# --- lists the spec does not order: sets --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "key"),
    [(n, k) for n in ANSWERS for k in _lists(n, UNORDERED.get(CASES[n]["tool"], ()))],
)
def test_an_unordered_list_in_any_order_matches_and_with_an_item_less_or_more_differs(
    name: str, key: str
) -> None:
    # answer on #133: neighbors edges and get links, aliases and external references are sets.
    cases, answers = _one(name)
    listed = answers[name]["data"][key]
    for order in (list(reversed(listed)), listed[1:] + listed[:1]):
        answers[name]["data"][key] = order
        assert differences(cases, answers) == []
    answers[name]["data"][key] = listed[:-1]
    assert differences(cases, answers)
    answers[name]["data"][key] = [*listed, copy.deepcopy(listed[0])]
    assert differences(cases, answers), "an item listed twice is not the same set of edges"


@pytest.mark.parametrize(
    ("name", "key"),
    [
        (n, k)
        for n in ANSWERS
        for k in UNORDERED.get(CASES[n]["tool"], ())
        if k in CASES[n]["answer"]["data"]
    ],
)
def test_an_unordered_list_item_changed_in_one_field_differs(name: str, key: str) -> None:
    # answer on #133: an unordered list still has to hold the expected items.
    listed = CASES[name]["answer"]["data"][key]
    if not listed:
        pytest.skip("this list is empty")
    cases, answers = _one(name)
    item = answers[name]["data"][key][0]
    field = next(k for k in item if isinstance(item[k], (str, int)))
    item[field] = f"{item[field]}x" if isinstance(item[field], str) else item[field] + 1
    assert differences(cases, answers)


@pytest.mark.parametrize("name", [n for n in ANSWERS if CASES[n]["tool"] == "neighbors"])
def test_the_neighbors_cases_never_cut_their_edges_so_the_set_does_not_depend_on_an_order(
    name: str,
) -> None:
    # section 8.2 cuts a list at its limit; which edges survive a cut would depend on an order the
    # spec does not fix (answer on #133), so a case compared as a set must not be cut.
    data = CASES[name]["answer"]["data"]
    assert len(data["edges"]) == data["total"], name


@pytest.mark.parametrize("name", [n for n in ANSWERS if CASES[n]["tool"] == "get"])
def test_the_get_cases_never_cut_the_lists_compared_as_sets(name: str) -> None:
    # section 8.2: the `*_total` fields count past a cut; a cut list compared as a set would hide
    # which items a kit keeps.
    data = CASES[name]["answer"]["data"]
    for key in UNORDERED["get"]:
        assert len(data[key]) == data[f"{key}_total"], f"{name}: {key}"


# --- lists the spec orders: lists ---------------------------------------------------------------


@pytest.mark.parametrize(("name", "key"), [(n, k) for n in ANSWERS for k in _lists(n, ORDERED)])
def test_an_ordered_list_in_another_order_differs(name: str, key: str) -> None:
    # sections 8.5 (tiers), 8.6 (rows, columns, edge cells), 3.6 (evidence): the order is data.
    cases, answers = _one(name)
    listed = answers[name]["data"][key]
    reversed_ = list(reversed(listed))
    if reversed_ == listed:
        pytest.skip("the list reads the same backwards")
    answers[name]["data"][key] = reversed_
    assert differences(cases, answers)
    answers[name]["data"][key] = listed[1:] + listed[:1]
    if answers[name]["data"][key] != listed:
        assert differences(cases, answers)


@pytest.mark.parametrize("name", [n for n in ANSWERS if CASES[n]["tool"] == "table"])
def test_the_cells_of_a_table_row_stay_in_the_order_of_the_columns(name: str) -> None:
    # section 8.1: the node's id, then one cell per column; rows are not sets either.
    data = CASES[name]["answer"]["data"]
    cases, answers = _one(name)
    rows = answers[name]["data"]["rows"]
    if not rows:
        pytest.skip("no rows")
    cells = next(
        (r for r in rows if isinstance(r, list) and len(set(map(json.dumps, r))) > 1), None
    )
    if cells is None:
        pytest.skip("no row of distinct cells")
    cells.reverse()
    assert differences(cases, answers), data["columns"]


def test_the_cells_of_an_edge_column_are_a_list_the_row_keeps_in_order() -> None:
    # section 8.6: an edge cell lists the labels of the other nodes in node id order.
    for name in ANSWERS:
        if CASES[name]["tool"] != "table":
            continue
        cases, answers = _one(name)
        for row in answers[name]["data"]["rows"]:
            for i, cell in enumerate(row):
                if isinstance(cell, list) and len(cell) > 1 and cell != cell[::-1]:
                    row[i] = cell[::-1]
                    assert differences(cases, answers), name
                    return
    pytest.skip("no case has an edge cell with two labels")


# --- errors -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ERRORS)
@pytest.mark.parametrize("message", ["", "x" * 400, "ü" * 400, "line\nbreak", "Artist:51"])
def test_any_error_message_matches(name: str, message: str) -> None:
    # answer on #133: the wording of an error is the kit's own.
    cases, answers = _one(name)
    answers[name]["error"]["message"] = message
    assert differences(cases, answers) == []


@pytest.mark.parametrize("name", ERRORS)
@pytest.mark.parametrize("code", ["", "UNKNOWN_ID", "unknown id", "unknown_ids", "ok", "path"])
def test_a_code_outside_the_schemas_list_never_matches(name: str, code: str) -> None:
    # answers.schema.json: the code is one of its six, even where the spec names none.
    assert code not in CODES
    cases, answers = _one(name)
    answers[name]["error"]["code"] = code
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ERRORS)
@pytest.mark.parametrize("code", [None, 7, ["unknown_id"], {"code": "unknown_id"}])
def test_a_code_that_is_no_string_never_matches(name: str, code: Any) -> None:
    cases, answers = _one(name)
    answers[name]["error"]["code"] = code
    assert differences(cases, answers)


@pytest.mark.parametrize(
    "name",
    [n for n in ERRORS if CASES[n]["answer"]["error"]["code"] in ("unknown_id", "unknown_column")],
)
@pytest.mark.parametrize("code", CODES)
def test_the_codes_the_spec_names_match_only_themselves(name: str, code: str) -> None:
    # section 8.1 (an unknown id is an error) and 8.6 (`unknown_column`).
    cases, answers = _one(name)
    answers[name]["error"]["code"] = code
    same = code == CASES[name]["answer"]["error"]["code"]
    assert (differences(cases, answers) == []) is same


@pytest.mark.parametrize(
    "name",
    [
        n
        for n in ERRORS
        if CASES[n]["answer"]["error"]["code"] not in ("unknown_id", "unknown_column")
    ],
)
@pytest.mark.parametrize("code", CODES)
def test_where_the_spec_names_no_code_every_code_of_the_schema_matches(
    name: str, code: str
) -> None:
    cases, answers = _one(name)
    answers[name]["error"]["code"] = code
    assert differences(cases, answers) == []


@pytest.mark.parametrize("name", [n for n in ERRORS if CASES[n]["answer"]["error"]["suggestions"]])
def test_the_first_expected_suggestion_may_come_anywhere_in_the_list(name: str) -> None:
    # answer on #133: the list must include the best match; where is up to the kit.
    cases, answers = _one(name)
    best = CASES[name]["answer"]["error"]["suggestions"][0]
    for suggestions in (
        [best],
        ["Zed:1", "Zed:2", "Zed:3", "Zed:4", best],
        [best, best],
    ):
        answers[name]["error"]["suggestions"] = suggestions
        assert differences(cases, answers) == [], suggestions


@pytest.mark.parametrize("name", [n for n in ERRORS if CASES[n]["answer"]["error"]["suggestions"]])
@pytest.mark.parametrize("other", ["Zed:1", "Zed:2", ""])
def test_a_list_of_suggestions_without_the_first_expected_one_differs(
    name: str, other: str
) -> None:
    cases, answers = _one(name)
    best = CASES[name]["answer"]["error"]["suggestions"][0]
    answers[name]["error"]["suggestions"] = [] if not other else [other + best]
    assert differences(cases, answers)


@pytest.mark.parametrize(
    "name", [n for n in ERRORS if not CASES[n]["answer"]["error"]["suggestions"]]
)
def test_an_error_with_no_expected_suggestion_takes_none_or_up_to_five_node_ids(name: str) -> None:
    # answers.schema.json: at most 5 ids; the cases expect none, so nothing is demanded.
    cases, answers = _one(name)
    answers[name]["error"]["suggestions"] = []
    assert differences(cases, answers) == []
    answers[name]["error"]["suggestions"] = [f"Zed:{i}" for i in range(5)]
    assert differences(cases, answers) == []
    answers[name]["error"]["suggestions"] = [f"Zed:{i}" for i in range(6)]
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ERRORS)
@pytest.mark.parametrize(
    "bad",
    [
        "artist:51",
        "Artist:",
        ":51",
        "51",
        "Artist",
        "A rtist:1",
        "Artist-1:2",
        "9Artist:1",
        " Artist:51",
        "",
    ],
)
def test_a_suggestion_that_is_no_node_id_by_the_schema_differs(name: str, bad: str) -> None:
    # answers.schema.json `id`: ^[A-Z][A-Za-z0-9]*:.+$, so a node type name, a colon, a key.
    cases, answers = _one(name)
    best = CASES[name]["answer"]["error"]["suggestions"][:1]
    answers[name]["error"]["suggestions"] = [*best, bad]
    assert differences(cases, answers)


@pytest.mark.parametrize("name", ERRORS)
def test_a_suggestion_of_512_characters_is_an_id_and_one_of_513_is_not(name: str) -> None:
    # answers.schema.json `id`: maxLength 512.
    cases, answers = _one(name)
    best = CASES[name]["answer"]["error"]["suggestions"][:1]
    answers[name]["error"]["suggestions"] = [*best, "Zed:" + "k" * (512 - 4)]
    assert not _rejected(cases, answers)
    answers[name]["error"]["suggestions"] = [*best, "Zed:" + "k" * (513 - 4)]
    assert _rejected(cases, answers)


@pytest.mark.parametrize("name", ERRORS)
def test_suggestions_must_be_nodes_of_the_mosaic_when_the_mosaic_is_known(name: str) -> None:
    # section 8.1: an unknown id names the closest matches from `find`: nodes that exist.
    cases, answers = _one(name)
    best = CASES[name]["answer"]["error"]["suggestions"][:1]
    answers[name]["error"]["suggestions"] = [*best, "Zed:1"]
    assert differences(cases, answers, node_ids={*best, "Other:1"})
    assert differences(cases, answers, node_ids={*best, "Zed:1"}) == []


@pytest.mark.parametrize("name", ERRORS)
def test_an_error_has_no_data_beside_it(name: str) -> None:
    # section 8.2 and answers.schema.json: an answer is `data` or an `error`, never both.
    cases, answers = _one(name)
    answers[name]["data"] = {}
    assert _rejected(cases, answers)


@pytest.mark.parametrize("name", ANSWERS)
def test_an_answer_has_no_error_beside_its_data(name: str) -> None:
    cases, answers = _one(name)
    answers[name]["error"] = {"code": "bad_argument", "message": "", "suggestions": []}
    assert _rejected(cases, answers)


@pytest.mark.parametrize("name", list(CASES))
def test_an_answer_with_a_top_level_field_more_differs(name: str) -> None:
    # section 8.2 / answers.schema.json: the envelope is tool, mosaic and data or error.
    cases, answers = _one(name)
    answers[name]["note"] = "extra"
    assert _rejected(cases, answers)


# --- the set of cases ----------------------------------------------------------------------------


def test_an_answer_for_a_name_that_is_no_case_and_a_case_with_no_answer_both_differ() -> None:
    names = list(CASES)
    answers = {n: copy.deepcopy(CASES[n]["answer"]) for n in names}
    assert differences(CASES, answers) == []
    answers["not-a-case"] = copy.deepcopy(answers[names[0]])
    assert any("not-a-case" in d for d in differences(CASES, answers))
    del answers["not-a-case"], answers[names[-1]]
    assert any(names[-1] in d for d in differences(CASES, answers))


def test_the_differences_name_every_case_that_differs_not_only_the_first() -> None:
    answers = {n: copy.deepcopy(CASES[n]["answer"]) for n in CASES}
    for n in ("get-track", "cite-node", "table-employee"):
        answers[n]["mosaic"] = "0" * 64
    found = differences(CASES, answers)
    for n in ("get-track", "cite-node", "table-employee"):
        assert any(d.startswith(f"{n}:") for d in found), n


def test_the_comparison_does_not_change_its_inputs() -> None:
    cases = copy.deepcopy(CASES)
    answers = {n: copy.deepcopy(CASES[n]["answer"]) for n in CASES}
    before = json.dumps([cases, answers], sort_keys=False)
    differences(cases, answers)
    assert json.dumps([cases, answers], sort_keys=False) == before
