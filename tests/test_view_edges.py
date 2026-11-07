"""Edge cases of ``mosaic view`` (M2.11), from docs/design.md (Viewer) and section 3.8.

Written from the spec's words: the file is opened read-only and unchanged (3.8 step 1), a missing
or refused file is an error naming it with exit status 1 and no page (steps 2 and 3), and the
page loads the mosaic with no query server. A stand-in for the built viewer is served.
"""

import _thread
import hashlib
import json
import shutil
import socket
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import pytest
from mosaic_build import view
from mosaic_build.cli import main

from tests.conftest import REPO

READING = REPO / "conformance" / "reading"
CASES = json.loads((READING / "cases.json").read_text(encoding="utf-8"))
REFUSED = sorted(name for name, case in CASES.items() if not case["opens"])


@pytest.fixture
def stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


class Visitor:
    """A browser stand-in: runs ``action(url)`` on a thread, then stops the command."""

    def __init__(self, action: Callable[[str], Any]) -> None:
        self.action = action
        self.urls: list[str] = []
        self.result: Any = None
        self.error: BaseException | None = None

    def __call__(self, url: str, *_: object, **__: object) -> bool:
        self.urls.append(url)

        def visit() -> None:
            try:
                self.result = self.action(url)
            except BaseException as e:
                self.error = e
            finally:
                _thread.interrupt_main()

        threading.Thread(target=visit, daemon=True).start()
        return True


def mosaic_address(page: str) -> str:
    (named,) = parse_qs(urlsplit(page).query)["mosaic"]
    return urljoin(page, named)


def fetch(url: str) -> tuple[int, bytes, dict[str, str]]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read(), dict(response.headers)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_view(
    path: Path | str, monkeypatch: pytest.MonkeyPatch, action: Callable[[str], Any]
) -> tuple[int, Visitor]:
    visitor = Visitor(action)
    monkeypatch.setattr("webbrowser.open", visitor)
    code = main(["view", str(path)])
    if visitor.error:
        raise visitor.error
    return code, visitor


@pytest.mark.parametrize(
    "name", ["100%.mosaic", "a?b.mosaic", "plus+sign.mosaic", "%2e%2e.mosaic", "a%2Fb.mosaic"]
)
def test_special_characters_in_a_file_name_reach_the_page_whole(
    name: str, tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # design.md (Viewer): the page loads the file the command was given.
    path = tmp_path / name
    shutil.copyfile(READING / "mosaic.mosaic", path)
    code, visitor = run_view(path, monkeypatch, lambda url: fetch(mosaic_address(url)))
    assert code == 0
    status, body, _ = visitor.result
    assert (status, body) == (200, path.read_bytes())
    assert unquote(mosaic_address(visitor.urls[0]).rsplit("/", 1)[1]) == name


def test_a_symlinked_file_is_served_and_its_target_is_unchanged(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 3.8 step 1: read-only; the file the user names is the file that is read.
    target = tmp_path / "real" / "m.mosaic"
    target.parent.mkdir()
    shutil.copyfile(READING / "mosaic.mosaic", target)
    link = tmp_path / "link.mosaic"
    link.symlink_to(target)
    before = (
        sha(target),
        target.stat().st_mtime_ns,
        sorted(p.name for p in target.parent.iterdir()),
    )
    code, visitor = run_view(link, monkeypatch, lambda url: fetch(mosaic_address(url)))
    assert code == 0
    assert visitor.result[:2] == (200, target.read_bytes())
    after = (
        sha(target),
        target.stat().st_mtime_ns,
        sorted(p.name for p in target.parent.iterdir()),
    )
    assert after == before and link.is_symlink()


def test_a_relative_path_opens_the_same_file(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The command takes FILE as typed; a relative path is a path.
    shutil.copyfile(READING / "mosaic.mosaic", tmp_path / "rel.mosaic")
    monkeypatch.chdir(tmp_path)
    code, visitor = run_view("rel.mosaic", monkeypatch, lambda url: fetch(mosaic_address(url)))
    assert code == 0
    assert visitor.result[:2] == (200, (tmp_path / "rel.mosaic").read_bytes())


def test_a_read_only_file_in_a_read_only_directory_opens_without_a_sidecar(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 3.8 step 1: opened read-only and immutable, even for a WAL-mode file (wal.mosaic).
    folder = tmp_path / "ro"
    folder.mkdir()
    path = folder / "wal.mosaic"
    shutil.copyfile(READING / "wal.mosaic", path)
    path.chmod(0o444)
    folder.chmod(0o555)
    try:
        code, visitor = run_view(path, monkeypatch, lambda url: fetch(mosaic_address(url)))
        names = sorted(p.name for p in folder.iterdir())
    finally:
        folder.chmod(0o755)
    assert code == 0
    assert visitor.result[:2] == (200, path.read_bytes())
    assert names == ["wal.mosaic"]


def test_the_server_listens_on_the_loopback_address_only(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # design.md: no query server; the page is served to this machine only.
    shutil.copyfile(READING / "mosaic.mosaic", tmp_path / "m.mosaic")

    def probe(url: str) -> bool:
        port = urlsplit(url).port
        assert port is not None
        with socket.socket() as s:
            s.settimeout(3)
            return s.connect_ex(("127.0.0.2", port)) == 0  # another loopback address

    code, visitor = run_view(tmp_path / "m.mosaic", monkeypatch, probe)
    assert code == 0 and visitor.result is False


def test_the_served_mosaic_has_its_length_and_repeated_requests_agree(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "m.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", path)

    def twice(url: str) -> list[tuple[int, bytes, dict[str, str]]]:
        return [fetch(mosaic_address(url)) for _ in range(3)]

    code, visitor = run_view(path, monkeypatch, twice)
    assert code == 0
    for status, body, headers in visitor.result:
        assert (status, body) == (200, path.read_bytes())
        assert int(headers["Content-Length"]) == path.stat().st_size


def test_the_server_is_stopped_when_the_command_returns(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "m.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", path)
    code, visitor = run_view(path, monkeypatch, lambda url: fetch(url)[0])
    assert code == 0 and visitor.result == 200
    port = urlsplit(visitor.urls[0]).port
    with socket.socket() as s:
        s.settimeout(3)
        assert s.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.parametrize(
    "content",
    [b"", b"\0" * 4096, b"SQLite format 3\0" + b"\0" * 84, b"x" * 100_000],
    ids=["zero-bytes", "nul-bytes", "header-only", "text"],
)
def test_garbage_files_are_refused_naming_the_file(
    content: bytes,
    tmp_path: Path,
    stand_in: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 3.8 step 2: a file that is not a conforming mosaic is refused: exit 1, no page.
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    path = tmp_path / "garbage.mosaic"
    path.write_bytes(content)
    assert main(["view", str(path)]) == 1
    captured = capsys.readouterr()
    assert str(path) in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert path.read_bytes() == content


@pytest.mark.parametrize("keep", [100, 1024, 4096, 8192])
def test_a_truncated_mosaic_is_refused(
    keep: int,
    tmp_path: Path,
    stand_in: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 3.8 steps 2 and 3: a cut file never opens, however much of it is left.
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    data = (READING / "mosaic.mosaic").read_bytes()
    assert keep < len(data)
    path = tmp_path / "cut.mosaic"
    path.write_bytes(data[:keep])
    assert main(["view", str(path)]) == 1
    err = capsys.readouterr().err
    assert str(path) in err and "Traceback" not in err


def test_a_refused_file_prints_nothing_on_stdout(
    stand_in: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No page, so no address is announced.
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    for name in REFUSED:
        assert main(["view", str(READING / name)]) == 1, name
        captured = capsys.readouterr()
        assert captured.out == "", name
        assert str(READING / name) in captured.err, name


def test_a_refused_file_is_refused_even_when_the_viewer_is_not_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(view, "VIEWER_DIST", tmp_path / "no-dist")
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    assert main(["view", str(READING / "node-changed.mosaic")]) == 1
    assert capsys.readouterr().err != ""


def test_view_with_two_files_is_a_usage_error(stand_in: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["view", str(READING / "mosaic.mosaic"), str(READING / "tessera.tessera")])
    assert exit_info.value.code == 2
