"""scripts/queue_labels.py: keeps the work-queue labels true after issues close and PRs merge."""

import importlib.util
import sys
from types import ModuleType

import pytest

from tests.conftest import REPO


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("queue_labels", REPO / "scripts/queue_labels.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["queue_labels"] = module
    spec.loader.exec_module(module)
    return module


ql = _load()

# The "Blocked by" line as the queue's issues write it.
BODY_14 = """Spec 0.1 §7.1 steps 1-3.

**Done when**
- Tests for priority order.

**Blocked by:** #9, #10, #47

_Follow CLAUDE.md._
"""


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (BODY_14, [9, 10, 47]),
        ("**Blocked by:** #6\n", [6]),
        ("Blocked by: #3, #18, #3", [3, 18]),
        ("blocked BY #12 and #13", [12, 13]),
        ("Nothing blocks this.", []),
        ("", []),
        (None, []),
        ("See #5 for context.\n**Blocked by:** #8", [8]),
    ],
)
def test_blockers_reads_the_blocked_by_line(body: str | None, expected: list[int]) -> None:
    assert ql.blockers(body) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Closes #7\n\n## Progress", [7]),
        ("Fixes #3, resolves #4. closed #5", [3, 4, 5]),
        ("Closes: #41", [41]),
        ("Refs #10. This PR is the spec only.", []),
        ("Closes #7 and Closes #7", [7]),
        (None, []),
    ],
)
def test_closing_refs(body: str | None, expected: list[int]) -> None:
    assert ql.closing_refs(body) == expected


def _issue(n: int, open_: bool, *labels: str, body: str = "") -> object:
    return ql.Issue(n, open_, frozenset(labels), body)


def test_unblocks_an_issue_once_every_blocker_is_closed() -> None:
    issues = {8: _issue(8, True, "blocked", "agent", body="**Blocked by:** #7")}
    p = ql.plan(issues, is_closed={7: True}.__getitem__)
    assert p.unblock == [8]


def test_keeps_an_issue_blocked_while_one_blocker_is_open() -> None:
    issues = {14: _issue(14, True, "blocked", body=BODY_14)}
    p = ql.plan(issues, is_closed={9: True, 10: False, 47: True}.__getitem__)
    assert p.unblock == []


def test_an_issue_without_a_blocked_by_line_stays_blocked() -> None:
    issues = {20: _issue(20, True, "blocked", body="No list here.")}
    assert ql.plan(issues, is_closed=lambda n: True).unblock == []


def test_a_merged_pr_closes_its_issue_and_that_unblocks_the_next() -> None:
    """The #7 case: PR #40 merged but #7 stayed open and in progress, so #8 stayed blocked."""
    issues = {
        7: _issue(7, True, "in-progress", "ready", "agent"),
        8: _issue(8, True, "blocked", "agent", body="**Blocked by:** #7"),
    }
    p = ql.plan(issues, is_closed=lambda n: False, to_close=[7])
    assert p.close == [7]
    assert p.remove == {7: ["in-progress", "ready"]}
    assert p.unblock == [8]


def test_closed_issues_lose_their_queue_labels() -> None:
    issues = {41: _issue(41, False, "ready", "m1"), 6: _issue(6, False, "agent", "m1")}
    assert ql.plan(issues, is_closed=lambda n: True).remove == {41: ["ready"]}


def test_does_not_close_what_is_already_closed_or_unknown() -> None:
    issues = {5: _issue(5, False, "agent")}
    assert ql.plan(issues, is_closed=lambda n: True, to_close=[5, 99]).close == []
