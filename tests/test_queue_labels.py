"""scripts/queue_labels.py: keeps the work-queue labels true after issues close and PRs merge."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

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


def _issue(n: int, open_: bool, *labels: str, body: str = "") -> Any:
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


# --- closing keywords: negation, code and quotes (#56) ---


@pytest.mark.parametrize(
    "body",
    [
        "This does not close #7; #8 does that.",
        "It doesn't fix #3.",
        "Do NOT resolve #4 here.",
        "Never closes #5.",
        "```\nCloses #7\n```",
        "~~~text\nFixes #3\n~~~",
        "> Closes #7\n",
        "Write `Closes #7` in the body.",
    ],
)
def test_closing_refs_ignores_negations_code_and_quotes(body: str) -> None:
    assert ql.closing_refs(body) == []


def test_closing_refs_reads_keywords_around_a_fenced_block() -> None:
    body = "Closes #7\n\n```\nCloses #8\n```\n\n> Fixes #9\n\nFixes #10, not #11"
    assert ql.closing_refs(body) == [7, 10]


def test_closing_refs_keeps_a_keyword_after_another_word_ending_in_not() -> None:
    assert ql.closing_refs("Knot closes #12") == [12]


# --- the triggering event (#56) ---


def _write_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: object) -> None:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))


def _pr_event(merged: bool, base: str = "main") -> dict[str, object]:
    return {
        "action": "closed",
        "pull_request": {
            "number": 40,
            "merged": merged,
            "body": "Closes #7\n\nNext step: none",
            "base": {"ref": base},
        },
        "repository": {"default_branch": "main"},
    }


def test_event_of_a_merged_pr_names_the_issues_it_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(tmp_path, monkeypatch, _pr_event(merged=True))
    assert ql._event() == ([7], [])


def test_event_of_an_unmerged_pr_closes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(tmp_path, monkeypatch, _pr_event(merged=False))
    assert ql._event() == ([], [])


def test_event_of_a_pr_merged_into_another_branch_closes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(tmp_path, monkeypatch, _pr_event(merged=True, base="issue-14-merge"))
    assert ql._event() == ([], [])


def test_event_of_a_closed_issue_names_that_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = {"action": "closed", "issue": {"number": 41, "state": "closed", "body": "Closes #9"}}
    _write_event(tmp_path, monkeypatch, event)
    assert ql._event() == ([], [41])


def test_event_of_a_closed_issue_that_is_a_pr_names_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = {"action": "closed", "issue": {"number": 40, "pull_request": {"url": "…"}}}
    _write_event(tmp_path, monkeypatch, event)
    assert ql._event() == ([], [])


def test_no_event_names_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert ql._event() == ([], [])
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "missing.json"))
    assert ql._event() == ([], [])


def test_event_of_a_manual_run_names_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(tmp_path, monkeypatch, {"inputs": {"dry_run": "true"}})
    assert ql._event() == ([], [])


# --- main() against a fake GitHub (#56) ---


class FakeGitHub:
    """Holds issues in memory; `fail_on` makes that write call (1-based) raise."""

    def __init__(self, *issues: Any, fail_on: int | None = None) -> None:
        self.state: dict[int, Any] = {i.number: i for i in issues}
        self.writes: list[tuple[str, int, str]] = []
        self.fail_on = fail_on

    def _write(self, what: str, number: int, arg: str = "") -> None:
        if self.fail_on == len(self.writes) + 1:
            raise OSError(f"{what} #{number} failed")
        self.writes.append((what, number, arg))

    def issue(self, number: int) -> Any:
        return self.state[number]

    def issues(self, state: str, label: str | None = None) -> list[Any]:
        return [
            i
            for _, i in sorted(self.state.items())
            if i.open == (state == "open") and (label is None or label in i.labels)
        ]

    def close(self, number: int) -> None:
        self._write("close", number)
        i = self.state[number]
        self.state[number] = ql.Issue(number, False, i.labels, i.body)

    def remove_label(self, number: int, label: str) -> None:
        self._write("remove", number, label)
        i = self.state[number]
        self.state[number] = ql.Issue(number, i.open, i.labels - {label}, i.body)

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._write("add", number, ",".join(labels))
        i = self.state[number]
        self.state[number] = ql.Issue(number, i.open, i.labels | set(labels), i.body)


def _labels(gh: FakeGitHub, n: int) -> frozenset[str]:
    return gh.state[n].labels


def test_main_unblocks_by_adding_ready_before_removing_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    gh = FakeGitHub(_issue(7, False, "agent"), _issue(8, True, "blocked", body="Blocked by: #7"))
    assert ql.main([], gh) == 0
    assert gh.writes == [("add", 8, "ready"), ("remove", 8, "blocked")]
    assert _labels(gh, 8) == {"ready"}


@pytest.mark.parametrize("fail_on", [1, 2])
def test_an_unblock_that_fails_halfway_keeps_the_issue_blocked(
    monkeypatch: pytest.MonkeyPatch, fail_on: int
) -> None:
    """Whichever call fails, the issue keeps `blocked`, so the next run finds it again."""
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    gh = FakeGitHub(
        _issue(7, False, "agent"),
        _issue(8, True, "blocked", body="Blocked by: #7"),
        fail_on=fail_on,
    )
    with pytest.raises(OSError):
        ql.main([], gh)
    assert "blocked" in _labels(gh, 8)
    retry = FakeGitHub(*gh.state.values())
    assert ql.main([], retry) == 0
    assert _labels(retry, 8) == {"ready"}


def test_main_closes_the_issues_a_merged_pr_names_and_tidies_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event(tmp_path, monkeypatch, _pr_event(merged=True))
    gh = FakeGitHub(
        _issue(7, True, "in-progress", "agent"),
        _issue(8, True, "blocked", body="**Blocked by:** #7"),
        _issue(41, False, "ready", "m1"),
    )
    assert ql.main([], gh) == 0
    assert gh.writes == [
        ("close", 7, ""),
        ("remove", 7, "in-progress"),
        ("remove", 41, "ready"),
        ("add", 8, "ready"),
        ("remove", 8, "blocked"),
    ]


def test_main_dry_run_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_event(tmp_path, monkeypatch, _pr_event(merged=True))
    gh = FakeGitHub(
        _issue(7, True, "in-progress"), _issue(8, True, "blocked", body="Blocked by: #7")
    )
    assert ql.main(["--dry-run"], gh) == 0
    assert gh.writes == []
    out = capsys.readouterr().out
    assert "close #7" in out and "#8: every blocker is closed" in out


# --- the workflow (#56) ---


def _workflow() -> dict[Any, Any]:
    data = yaml.safe_load((REPO / ".github/workflows/queue-labels.yml").read_text("utf-8"))
    assert isinstance(data, dict)
    return data


def test_workflow_concurrency_group_is_per_event() -> None:
    """One shared group keeps one pending run and cancels older ones: a lost PR event would
    lose its `Closes #n`. Every operation is idempotent, so per-event groups may overlap."""
    concurrency = _workflow()["concurrency"]
    assert isinstance(concurrency, dict)
    group = concurrency["group"]
    assert isinstance(group, str)
    assert "github.event.pull_request.number" in group
    assert "github.event.issue.number" in group
    assert "github.run_id" in group
    assert concurrency.get("cancel-in-progress") is False


def test_workflow_acts_only_on_prs_merged_into_the_default_branch() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    condition = jobs["labels"]["if"]
    assert "github.event.pull_request.merged" in condition
    assert (
        "github.event.pull_request.base.ref == github.event.repository.default_branch" in condition
    )
