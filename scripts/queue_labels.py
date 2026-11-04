"""Keep the work-queue labels true after issues close and pull requests merge.

Run by `.github/workflows/queue-labels.yml` on every closed issue and pull request, whoever
closed or merged it, and by hand with `workflow_dispatch`:

1. A pull request merged into the default branch closes the open issues its body names with
   `Closes #n` (also `Fixes`, `Resolves`), in case GitHub did not. Keywords after "not" or
   "never", in code (fenced or inline) and in quoted lines close nothing.
2. Closed issues lose `in-progress`, `ready` and `blocked`.
3. An open issue labelled `blocked` whose "Blocked by" list is all closed gets `ready` instead:
   `ready` is added before `blocked` is removed, so a run that fails halfway leaves the issue
   `blocked` and the next run finds it again.

Standard library only. Needs GITHUB_TOKEN (issues: write) and GITHUB_REPOSITORY; reads the
event from GITHUB_EVENT_PATH when there is one. `--dry-run` prints the changes without making them.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

API = "https://api.github.com"
QUEUE_LABELS = ("in-progress", "ready", "blocked")
BLOCKED_BY = re.compile(r"^\W*blocked by[^#\n]*(?P<refs>[^\n]*)$", re.IGNORECASE | re.MULTILINE)
CLOSING = re.compile(
    r"(?P<negation>(?:\bnot|\bnever|n't)\s+)?"
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(?P<number>\d+)\b",
    re.IGNORECASE,
)
FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")
QUOTE = re.compile(r"^ {0,3}>")
INLINE_CODE = re.compile(r"(?P<ticks>`+)(?!`).*?(?<!`)(?P=ticks)(?!`)")
REF = re.compile(r"#(\d+)\b")


def blockers(body: str | None) -> list[int]:
    """The issue numbers on the issue's "Blocked by" line, in order, without repeats."""
    match = BLOCKED_BY.search(body or "")
    if match is None:
        return []
    return list(dict.fromkeys(int(n) for n in REF.findall(match.group("refs"))))


def _prose(body: str) -> str:
    """The body without fenced code blocks, quoted lines and inline code spans."""
    lines: list[str] = []
    fence = ""
    for line in body.splitlines():
        match = FENCE.match(line)
        if fence:
            if (
                match
                and match["fence"][0] == fence[0]
                and len(match["fence"]) >= len(fence)
                and not line[match.end() :].strip()
            ):
                fence = ""  # the closing fence: same character, at least as long, nothing after
            continue
        if match:
            fence = match.group("fence")
            continue
        if QUOTE.match(line):
            continue
        lines.append(INLINE_CODE.sub(" ", line))
    return "\n".join(lines)


def closing_refs(body: str | None) -> list[int]:
    """The issue numbers a pull request body closes (`Closes #n`, `Fixes #n`, `Resolves #n`).

    Like GitHub, only prose counts: not fenced code, inline code or quoted lines. A keyword
    right after "not", "never" or "n't" ("does not close #7") closes nothing.
    """
    found = (m for m in CLOSING.finditer(_prose(body or "")) if not m.group("negation"))
    return list(dict.fromkeys(int(m.group("number")) for m in found))


@dataclass(frozen=True)
class Issue:
    number: int
    open: bool
    labels: frozenset[str]
    body: str = ""


@dataclass
class Plan:
    close: list[int] = field(default_factory=list)
    remove: dict[int, list[str]] = field(default_factory=dict)
    unblock: list[int] = field(default_factory=list)


def plan(
    issues: Mapping[int, Issue],
    is_closed: Callable[[int], bool],
    to_close: Iterable[int] = (),
) -> Plan:
    """What to change.

    `issues` holds the issues to tidy (closed ones) and to unblock (open ones labelled `blocked`);
    `is_closed` answers for any issue a "Blocked by" list names, after `to_close` is applied.
    """
    p = Plan()
    p.close = sorted(n for n in set(to_close) if n in issues and issues[n].open)
    closing = set(p.close)
    for n in sorted(issues):
        issue = issues[n]
        if not issue.open or n in closing:
            stale = sorted(set(QUEUE_LABELS) & issue.labels)
            if stale:
                p.remove[n] = stale
        elif "blocked" in issue.labels:
            refs = blockers(issue.body)
            if refs and all(r in closing or is_closed(r) for r in refs):
                p.unblock.append(n)
    return p


class GitHub:
    def __init__(self, token: str, repo: str) -> None:
        self.token = token
        self.repo = repo

    def _call(self, method: str, path: str, data: object = None) -> object:
        request = urllib.request.Request(
            f"{API}/repos/{self.repo}{path}",
            method=method,
            data=None if data is None else json.dumps(data).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "mosaic-queue-labels",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            if method == "DELETE" and e.code == 404:  # label already gone
                return None
            raise
        return json.loads(raw) if raw else None

    def issue(self, number: int) -> Issue:
        data = self._call("GET", f"/issues/{number}")
        assert isinstance(data, dict)
        return _issue(data)

    def issues(self, state: str, label: str | None = None) -> list[Issue]:
        found: list[Issue] = []
        page = 1
        while True:
            query = {"state": state, "per_page": "100", "page": str(page)}
            if label:
                query["labels"] = label
            data = self._call("GET", f"/issues?{urllib.parse.urlencode(query)}")
            assert isinstance(data, list)
            found += [_issue(d) for d in data if "pull_request" not in d]
            if len(data) < 100:
                return found
            page += 1

    def close(self, number: int) -> None:
        self._call("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": "completed"})

    def remove_label(self, number: int, label: str) -> None:
        self._call("DELETE", f"/issues/{number}/labels/{urllib.parse.quote(label)}")

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._call("POST", f"/issues/{number}/labels", {"labels": labels})


def _issue(data: Mapping[str, object]) -> Issue:
    labels = data.get("labels") or []
    assert isinstance(labels, list)
    names = frozenset(str(label["name"]) for label in labels if isinstance(label, dict))
    number, state, body = data["number"], data["state"], data.get("body")
    assert isinstance(number, int)
    return Issue(number, state == "open", names, body if isinstance(body, str) else "")


def _event() -> tuple[list[int], list[int]]:
    """From the triggering event: issues a merged pull request closes, and a closed issue."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8") as f:
        event = json.load(f)
    pr = event.get("pull_request")
    if isinstance(pr, dict):
        base = pr.get("base")
        default = (event.get("repository") or {}).get("default_branch")
        into_default = isinstance(base, dict) and base.get("ref") == default
        if pr.get("merged") and into_default:
            return closing_refs(pr.get("body")), []
        return [], []
    issue = event.get("issue")
    if isinstance(issue, dict) and "pull_request" not in issue:
        return [], [int(issue["number"])]
    return [], []


def main(argv: list[str], gh: GitHub | None = None) -> int:
    dry_run = "--dry-run" in argv
    if gh is None:
        gh = GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    to_close, closed_now = _event()

    issues: dict[int, Issue] = {i.number: i for i in gh.issues("open", "blocked")}
    for n in [*to_close, *closed_now]:
        issues.setdefault(n, gh.issue(n))
    for label in QUEUE_LABELS:  # closed issues that still carry a queue label
        issues.update({i.number: i for i in gh.issues("closed", label)})

    states: dict[int, bool] = {n: not i.open for n, i in issues.items()}

    def is_closed(n: int) -> bool:
        if n not in states:
            states[n] = not gh.issue(n).open
        return states[n]

    p = plan(issues, is_closed, to_close)
    for n in p.close:
        print(f"close #{n} (its pull request merged)")
        if not dry_run:
            gh.close(n)
    for n, labels in p.remove.items():
        print(f"#{n} is closed: remove {', '.join(labels)}")
        if not dry_run:
            for label in labels:
                gh.remove_label(n, label)
    for n in p.unblock:
        print(f"#{n}: every blocker is closed, blocked -> ready")
        if not dry_run:
            gh.add_labels(n, ["ready"])  # first: a failure after it leaves `blocked`
            gh.remove_label(n, "blocked")
    if not (p.close or p.remove or p.unblock):
        print("nothing to change")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
