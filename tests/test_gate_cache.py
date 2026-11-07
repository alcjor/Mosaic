"""The gate cache in .claude/hooks: the fast gate runs once per exact working tree that passes.

Each test copies the hooks into a fresh git repository whose scripts/check-fast.sh is a stand-in
that counts its runs in a file outside the repository and passes or fails on request.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".claude" / "hooks"

FAKE_GATE = """#!/usr/bin/env bash
echo run >> "$GATE_RUNS"
[ "${GATE_FAILS:-}" = 1 ] && { echo "gate failed" >&2; exit 1; }
exit 0
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copytree(HOOKS, root / ".claude" / "hooks")
    gate = root / "scripts" / "check-fast.sh"
    gate.write_text(FAKE_GATE, encoding="utf-8")
    gate.chmod(0o755)
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return root


def run_hook(repo: Path, hook: str, payload: dict, **env: str) -> subprocess.CompletedProcess:
    full_env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(repo),
        "GATE_RUNS": str(repo.parent / "runs.txt"),
    }
    full_env.pop("MOSAIC_GATE_NOCACHE", None)
    full_env.update(env)
    return subprocess.run(
        [str(repo / ".claude" / "hooks" / hook)],
        input=json.dumps(payload),
        env=full_env,
        capture_output=True,
        text=True,
    )


def push(repo: Path, **env: str) -> subprocess.CompletedProcess:
    return run_hook(repo, "pre-push-check.sh", {"tool_input": {"command": "git push"}}, **env)


def stop(repo: Path, **env: str) -> subprocess.CompletedProcess:
    return run_hook(repo, "stop-check.sh", {"stop_hook_active": False}, **env)


def runs(repo: Path) -> int:
    path = repo.parent / "runs.txt"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def test_a_second_push_of_the_same_tree_skips_the_gate(repo: Path) -> None:
    assert push(repo).returncode == 0
    assert push(repo).returncode == 0
    assert runs(repo) == 1


def test_a_stop_after_a_passing_push_of_the_same_tree_skips_the_gate(repo: Path) -> None:
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    assert push(repo).returncode == 0
    assert stop(repo).returncode == 0
    assert runs(repo) == 1


def test_a_changed_tracked_file_runs_the_gate_again(repo: Path) -> None:
    push(repo)
    (repo / "a.txt").write_text("b\n", encoding="utf-8")
    push(repo)
    assert runs(repo) == 2


def test_a_new_untracked_file_runs_the_gate_again(repo: Path) -> None:
    push(repo)
    (repo / "test_new.py").write_text("x = 1\n", encoding="utf-8")
    push(repo)
    assert runs(repo) == 2


def test_a_file_git_ignores_does_not_run_the_gate_again(repo: Path) -> None:
    push(repo)
    (repo / "ignored").mkdir()
    (repo / "ignored" / "out.bin").write_text("x\n", encoding="utf-8")
    push(repo)
    assert runs(repo) == 1


def test_a_failing_gate_is_not_remembered_and_blocks_each_time(repo: Path) -> None:
    first = push(repo, GATE_FAILS="1")
    second = push(repo, GATE_FAILS="1")
    assert first.returncode == 2 and second.returncode == 2
    assert "gate failed" in second.stderr
    assert runs(repo) == 2


def test_a_pass_after_a_failure_is_remembered(repo: Path) -> None:
    push(repo, GATE_FAILS="1")
    push(repo)
    push(repo)
    assert runs(repo) == 2


def test_nocache_forces_a_full_run(repo: Path) -> None:
    push(repo)
    push(repo, MOSAIC_GATE_NOCACHE="1")
    assert runs(repo) == 2


def test_the_cache_leaves_the_staging_area_alone(repo: Path) -> None:
    (repo / "staged.txt").write_text("s\n", encoding="utf-8")
    git(repo, "add", "staged.txt")
    (repo / "unstaged.txt").write_text("u\n", encoding="utf-8")
    push(repo)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert sorted(status) == ["?? unstaged.txt", "A  staged.txt"]


def test_the_cache_is_kept_inside_git_and_never_in_the_tree(repo: Path) -> None:
    push(repo)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert status == ""
    assert (repo / ".git" / "mosaic-gate-pass").is_file()


def test_a_command_that_is_not_a_push_runs_nothing(repo: Path) -> None:
    result = run_hook(repo, "pre-push-check.sh", {"tool_input": {"command": "git status"}})
    assert result.returncode == 0
    assert runs(repo) == 0
