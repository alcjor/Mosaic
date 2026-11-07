"""Edge cases of the kit tool cases, checked without a mosaic (plan M3.4; verifier).

Written from Specification 0.1 sections 8.1, 8.2, 8.5, 8.6 and 11 and ``spec/answers.schema.json``,
not from the kit: what each expected answer in ``conformance/tools/expected-answers.json`` must
satisfy by the spec's words alone (list cuts and totals, tier order, ordering and ties by UTF-8
bytes, filters, pages, the cut marker, errors), plus the file's own hygiene (no case name or
argument given twice, since JSON readers keep the last of two equal keys without a word).
"""

import itertools
import json
import re
from typing import Any

import pytest

from tests.fixtures.tool_cases import FILE, load

DATA = load()
CASES: dict[str, Any] = DATA["cases"]
MARKER = "…"
TIER_ORDER = {"exact": 0, "text": 1, "vector": 2}
ID = re.compile(r"^[A-Z][A-Za-z0-9]*:.+$")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    names = [k for k, _ in pairs]
    assert len(names) == len(set(names)), f"a key given twice: {sorted(names)}"
    return dict(pairs)


def _by(text: str) -> bytes:
    return text.encode("utf-8")


def _cases(tool: str, kind: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (n, c)
        for n, c in CASES.items()
        if c["tool"] == tool and (kind in c["answer"] or kind == "any")
    ]


def _answered(tool: str) -> list[str]:
    return [n for n, _ in _cases(tool, "data")]


# --- the file -----------------------------------------------------------------------------------


def test_no_key_of_the_cases_file_is_given_twice() -> None:
    """JSON readers keep the last of two equal keys: a case name given twice would hide one."""
    json.loads(FILE.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)


def test_case_names_are_plain_and_not_empty() -> None:
    for name in CASES:
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", name), name


def test_the_file_is_utf8_without_a_byte_order_mark_and_ends_in_a_newline() -> None:
    raw = FILE.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n")
    assert b"\r" not in raw, "line endings are LF (CLAUDE.md, Rules for every change)"


def test_every_case_is_a_distinct_call() -> None:
    """Two cases with the same tool and arguments would be one case twice."""
    seen: dict[str, str] = {}
    for name, case in CASES.items():
        key = case["tool"] + json.dumps(case["arguments"], sort_keys=True, ensure_ascii=False)
        assert key not in seen, f"{name} repeats {seen[key]}"
        seen[key] = name


def test_every_answer_has_exactly_the_envelope_of_section_8_2() -> None:
    for name, case in CASES.items():
        answer = case["answer"]
        assert {"tool", "mosaic"} <= set(answer), name
        assert ("data" in answer) != ("error" in answer), f"{name}: data or error, never both"


def test_the_cases_use_no_argument_value_the_json_has_no_such_kind_for() -> None:
    """Section 8.1: arguments are JSON; no NaN or Infinity, which JSON does not have."""
    raw = FILE.read_text(encoding="utf-8")
    assert not re.search(r"\b(NaN|-?Infinity)\b", raw)


# --- lists are cut with the total (section 8.2) -------------------------------------------------


def _limit(case: dict[str, Any]) -> int:
    """Section 8.1 and 8.2: the default is 20 and no list is longer than 20."""
    return min(20, case["arguments"].get("limit", 20))


@pytest.mark.parametrize("name", [n for n, _ in _cases("find", "data")])
def test_a_find_answer_holds_at_most_limit_results_and_a_total_not_below_them(name: str) -> None:
    case = CASES[name]
    data = case["answer"]["data"]
    assert len(data["results"]) <= _limit(case)
    assert data["total"] >= len(data["results"])


@pytest.mark.parametrize("name", [n for n, _ in _cases("neighbors", "data")])
def test_a_neighbors_answer_holds_at_most_limit_edges_and_all_when_the_total_fits(
    name: str,
) -> None:
    case = CASES[name]
    data = case["answer"]["data"]
    assert len(data["edges"]) == min(_limit(case), data["total"])


@pytest.mark.parametrize("name", [n for n, _ in _cases("cite", "data")])
def test_a_cite_answer_lists_every_evidence_row_when_the_total_fits(name: str) -> None:
    data = CASES[name]["answer"]["data"]
    assert len(data["evidence"]) == min(20, data["total"])
    assert data["total"] >= 1, "every node and every edge has at least one evidence row (3.5)"


@pytest.mark.parametrize("name", _answered("table"))
def test_a_table_page_holds_20_rows_and_the_last_page_the_rest(name: str) -> None:
    """Section 8.6: each page holds 20 rows; ``total`` counts every node ``where`` keeps."""
    case = CASES[name]
    data = case["answer"]["data"]
    page = case["arguments"].get("page", 1)
    assert data["page"] == page
    assert len(data["rows"]) == max(0, min(20, data["total"] - 20 * (page - 1)))


# --- find: tiers and ties (section 8.5) ---------------------------------------------------------


@pytest.mark.parametrize("name", _answered("find"))
def test_find_results_are_listed_tier_by_tier_each_node_once(name: str) -> None:
    results = CASES[name]["answer"]["data"]["results"]
    tiers = [TIER_ORDER[r["match"]] for r in results]
    assert tiers == sorted(tiers), "exact, then text, then vector (8.5)"
    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)), "a vector match 'not already listed' is not listed twice"


@pytest.mark.parametrize("name", _answered("find"))
def test_find_exact_matches_are_in_id_order(name: str) -> None:
    """Section 8.5: within a tier ties break by id; an exact tier has no engine order, so ids."""
    exact = [r["id"] for r in CASES[name]["answer"]["data"]["results"] if r["match"] == "exact"]
    assert exact == sorted(exact, key=_by)


@pytest.mark.parametrize("name", _answered("find"))
def test_find_results_keep_to_the_type_asked_for_and_name_their_own_type(name: str) -> None:
    case = CASES[name]
    for result in case["answer"]["data"]["results"]:
        assert result["id"].split(":", 1)[0] == result["type"], "an id is <type>:<key> (3.4)"
        wanted = case["arguments"].get("type")
        assert wanted is None or result["type"] == wanted


@pytest.mark.parametrize("name", _answered("find"))
def test_find_exact_match_by_id_names_the_node_whose_id_is_the_query(name: str) -> None:
    case = CASES[name]
    query = case["arguments"]["query"]
    for result in case["answer"]["data"]["results"]:
        if result["match"] == "exact" and ID.match(query):
            assert result["id"] == query


def test_a_find_with_an_empty_query_is_not_an_error_the_cases_decide_to_return_nothing() -> None:
    """Guards the case list: the empty query's expected answer is an empty list with total 0."""
    empty = [c for c in CASES.values() if c["tool"] == "find" and c["arguments"]["query"] == ""]
    for case in empty:
        assert case["answer"].get("data") == {"results": [], "total": 0}


# --- text is length-limited and cut with a marker (section 8.2) -----------------------------------


def _strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        return [s for i, v in enumerate(value) for s in _strings(v, f"{path}[{i}]")]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(v, f"{path}.{k}")]
    return []


def test_every_label_is_at_most_120_characters_or_cut_to_120_with_the_marker() -> None:
    for name, case in CASES.items():
        data = case["answer"].get("data", {})
        labels = [r["label"] for r in data.get("results", []) + data.get("edges", [])]
        labels += [data["label"]] if "label" in data else []
        for label in labels:
            if label is None:
                continue
            assert len(label) <= 121, name
            if len(label) == 121:
                assert label.endswith(MARKER), f"{name}: a cut label ends in the marker"


def test_every_snippet_is_at_most_600_characters_and_a_summary_400() -> None:
    for name, case in CASES.items():
        data = case["answer"].get("data", {})
        for row in data.get("evidence", []):
            if row["snippet"] is not None:
                assert len(row["snippet"]) <= 601, name
                assert len(row["snippet"]) != 601 or row["snippet"].endswith(MARKER)
        if "summary" in data and data["summary"] is not None:
            assert len(data["summary"]) <= 401
            assert len(data["summary"]) != 401 or data["summary"].endswith(MARKER)


def test_no_text_of_an_answer_holds_a_control_character_the_host_could_read_as_a_line() -> None:
    """Section 8.2: text from the file must not sit where the host reads instructions.

    Labels and ids are one line: an answer whose id or label held a newline could break out of
    the data that carries it when a host prints it."""
    for name, case in CASES.items():
        data = case["answer"].get("data", {})
        for r in data.get("results", []) + data.get("edges", []):
            for field in ("id", "label"):
                assert "\n" not in (r.get(field) or "") and "\x00" not in (r.get(field) or ""), name


# --- get (section 8.1) --------------------------------------------------------------------------


@pytest.mark.parametrize("name", _answered("get"))
def test_get_links_are_one_per_edge_type_and_direction_each_counted(name: str) -> None:
    data = CASES[name]["answer"]["data"]
    pairs = [(link["edge"], link["direction"]) for link in data["links"]]
    assert len(pairs) == len(set(pairs))
    assert data["links_total"] == len(data["links"]) <= 20
    assert data["aliases_total"] == len(data["aliases"])
    assert data["external_refs_total"] == len(data["external_refs"])
    assert data["id"] == CASES[name]["arguments"]["id"]
    assert data["id"].split(":", 1)[0] == data["type"]


# --- neighbors (section 8.1) --------------------------------------------------------------------


@pytest.mark.parametrize("name", _answered("neighbors"))
def test_neighbors_edges_are_the_edge_and_direction_asked_for_with_no_edge_twice(
    name: str,
) -> None:
    case = CASES[name]
    arguments = case["arguments"]
    data = case["answer"]["data"]
    assert data["id"] == arguments["id"]
    keys = [(e["edge"], e["direction"], e["id"], e.get("qualifier", "")) for e in data["edges"]]
    assert len(keys) == len(set(keys))
    for edge in data["edges"]:
        if "edge" in arguments:
            assert edge["edge"] == arguments["edge"]
        if arguments.get("direction", "both") != "both":
            assert edge["direction"] == arguments["direction"]


# --- table (section 8.6) ------------------------------------------------------------------------


def _cell(case: dict[str, Any], row: list[Any], column: str) -> Any:
    return row[case["answer"]["data"]["columns"].index(column)]


def _holds(cell: Any, op: str, value: Any) -> bool:
    """Section 8.6, ``where``: a value is compared only with a value of its own kind."""
    same = (
        (isinstance(cell, bool) and isinstance(value, bool))
        or (
            isinstance(cell, (int, float))
            and not isinstance(cell, bool)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        )
        or (isinstance(cell, str) and isinstance(value, str))
    )
    if op == "contains":
        if isinstance(cell, str):
            return str(value).lower() in cell.lower()
        if isinstance(cell, list):
            return any(isinstance(i, str) and str(value).lower() in i.lower() for i in cell)
        return False
    if op == "!=":
        return not (same and cell == value)
    if not same:
        return False
    if isinstance(cell, str):
        cell, value = _by(cell), _by(value)
    return {
        "=": cell == value,
        "<": cell < value,
        "<=": cell <= value,
        ">": cell > value,
        ">=": cell >= value,
    }[op]


@pytest.mark.parametrize("name", _answered("table"))
def test_table_columns_start_with_id_and_name_each_column_once(name: str) -> None:
    case = CASES[name]
    data = case["answer"]["data"]
    columns = data["columns"]
    assert columns[0] == "id"
    assert len(columns) == len(set(columns)) <= 21
    wanted = case["arguments"].get("columns")
    if wanted is not None:
        assert columns[1:] == wanted
    assert all(len(row) == len(columns) for row in data["rows"])
    assert data["type"] == case["arguments"]["type"]


@pytest.mark.parametrize("name", _answered("table"))
def test_table_rows_are_nodes_of_the_type_each_once(name: str) -> None:
    data = CASES[name]["answer"]["data"]
    ids = [row[0] for row in data["rows"]]
    assert len(ids) == len(set(ids))
    assert all(i.startswith(f"{data['type']}:") for i in ids)


@pytest.mark.parametrize(
    "name", [n for n in _answered("table") if "order" not in CASES[n]["arguments"]]
)
def test_table_rows_without_order_are_in_id_order_by_utf8_bytes(name: str) -> None:
    case = CASES[name]
    ids = [row[0] for row in case["answer"]["data"]["rows"]]
    assert ids == sorted(ids, key=_by), "section 8.6: calls without order go by id (UTF-8 bytes)"


@pytest.mark.parametrize("name", _answered("table"))
def test_table_rows_keep_the_condition_the_call_gave(name: str) -> None:
    case = CASES[name]
    where = case["arguments"].get("where")
    if where is None:
        return
    conditions = where if isinstance(where, list) else [where]
    for row in case["answer"]["data"]["rows"]:
        for condition in conditions:
            cell = _cell(case, row, condition["column"])
            assert _holds(cell, condition["op"], condition["value"]), (row[0], condition)


@pytest.mark.parametrize("name", _answered("table"))
def test_table_rows_are_in_the_order_the_call_gave_with_ties_by_id(name: str) -> None:
    case = CASES[name]
    order = case["arguments"].get("order")
    if order is None:
        return
    orders = order if isinstance(order, list) else [order]
    orders = [{"column": o, "direction": "asc"} if isinstance(o, str) else o for o in orders]
    rows = case["answer"]["data"]["rows"]

    def group(value: Any) -> tuple[int, Any]:
        if value is None:
            return (5, 0)
        if isinstance(value, bool):
            return (0, value)
        if isinstance(value, (int, float)):
            return (1, value)
        if isinstance(value, str):
            return (2, _by(value))
        if isinstance(value, list):
            return (3, _by(json.dumps(value, ensure_ascii=False)))
        return (4, _by(json.dumps(value, ensure_ascii=False)))

    for earlier, later in itertools.pairwise(rows):
        for o in orders:
            a, b = (_cell(case, r, o["column"]) for r in (earlier, later))
            ga, gb = group(a), group(b)
            if ga == gb:
                continue
            if o.get("direction", "asc") == "desc" and ga[0] == gb[0] and ga[0] != 5:
                ga, gb = gb, ga
            assert ga < gb, (earlier[0], later[0], o)
            break
        else:
            assert _by(earlier[0]) < _by(later[0]), "ties go by id"


# --- cite (section 8.1, 3.5) --------------------------------------------------------------------


@pytest.mark.parametrize("name", _answered("cite"))
def test_cite_subject_is_the_node_or_edge_the_call_named(name: str) -> None:
    case = CASES[name]
    subject = case["answer"]["data"]["subject"]
    arguments = case["arguments"]
    if "id" in arguments:
        assert subject == arguments["id"]
    else:
        assert subject == {
            k: arguments[k] for k in ("from", "type", "to", "qualifier") if k in arguments
        }


@pytest.mark.parametrize("name", _answered("cite"))
def test_cite_evidence_follows_the_locator_and_method_rules_of_section_3_5(name: str) -> None:
    for row in CASES[name]["answer"]["data"]["evidence"]:
        for pair in row["locator"].split(";"):
            assert re.fullmatch(r"[a-z]+=[^;=]+", pair), (name, row["locator"])
        if row["method"] == "extracted":
            assert row["confidence"] is None, "an extracted row has NULL confidence (3.5)"
        else:
            assert row["confidence"] is not None
        assert "via" not in row or not row["via"], "a mosaic without mosaic pieces has no via"


def test_the_cited_source_hash_is_one_hash_for_the_one_source_of_the_mosaic() -> None:
    hashes = {
        row["source_hash"]
        for c in CASES.values()
        for row in c["answer"].get("data", {}).get("evidence", [])
    }
    assert len(hashes) == 1


# --- errors (sections 8.1, 8.2 and the schema) --------------------------------------------------


@pytest.mark.parametrize("name", [n for n, _ in _cases("any", "error")])
def test_an_error_names_what_failed_and_keeps_to_the_schema_bounds(name: str) -> None:
    error = CASES[name]["answer"]["error"]
    assert error["message"].strip()
    assert len(error["message"]) <= 400
    assert len(error["suggestions"]) <= 5
    assert len(set(error["suggestions"])) == len(error["suggestions"])


@pytest.mark.parametrize("name", [n for n, _ in _cases("any", "error")])
def test_an_error_about_an_unknown_name_quotes_it(name: str) -> None:
    """Errors name what failed (CLAUDE.md, Style): the bad id, type, edge or column."""
    case = CASES[name]
    error = case["answer"]["error"]
    culprit = {
        "unknown_id": case["arguments"].get("id"),
        "unknown_type": case["arguments"].get("type"),
        "unknown_edge": case["arguments"].get("edge"),
    }.get(error["code"])
    if culprit is not None:
        assert culprit in error["message"], (name, error["message"])


def test_an_unknown_id_error_comes_for_every_tool_that_takes_an_id_the_cases_cover() -> None:
    """Section 8.1 says an unknown id is an error for the tools that take one."""
    covered = {
        c["tool"]
        for c in CASES.values()
        if c["answer"].get("error", {}).get("code") == "unknown_id"
    }
    assert {"get", "cite"} <= covered
    assert "neighbors" in covered, "neighbors takes an id too: no case shows its unknown_id"


def test_a_cite_of_an_edge_that_does_not_exist_is_an_error_not_an_empty_list() -> None:
    """Section 8.1 forbids an empty success for an unknown id; the same holds for an edge."""
    edge_errors = [
        c
        for c in CASES.values()
        if c["tool"] == "cite" and "from" in c["arguments"] and "error" in c["answer"]
    ]
    assert edge_errors, "no case cites an edge that does not exist"
