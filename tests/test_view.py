"""``mosaic view`` (M2.11): opens the viewer page with a mosaic loaded, with no query server.

docs/design.md (Implementation plan: Viewer); Specification 0.1, section 3.8. The command
applies the reading rules (steps 1 to 3) itself before a page opens; a missing or refused file
is an error naming the file and what failed, with exit status 1. The page's kit refuses the
same files by the same rules: ``kit/test/open.test.ts`` and ``kit/test/hashes.test.ts`` (M2.1,
M2.2) read the same ``conformance/reading/`` cases.

These tests serve a stand-in for the built viewer; ``tests/viewer/test_view_page.py`` (slow)
builds the real one and opens it in Chromium.
"""

import _thread
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import pytest
from mosaic_build import view
from mosaic_build.cli import main
from mosaic_format.file import SIDECARS

from tests.conftest import REPO
from tests.test_cli import entry_point

READING = REPO / "conformance" / "reading"
CASES = json.loads((READING / "cases.json").read_text(encoding="utf-8"))
REFUSED = sorted(name for name, case in CASES.items() if not case["opens"])
OPENS = sorted(name for name, case in CASES.items() if case["opens"])


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the built viewer: a page and one asset."""
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    (directory / "assets" / "page.js").write_text("export {};", encoding="utf-8")
    (directory / "assets" / "engine.wasm").write_bytes(b"\0asm")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def get(url: str) -> tuple[int, bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, b"", ""


def mosaic_url(page: str) -> str:
    """The mosaic's address, as the page resolves its ``?mosaic=`` against its own."""
    (named,) = parse_qs(urlsplit(page).query)["mosaic"]
    return urljoin(page, named)


class Browser:
    """Stands in for ``webbrowser.open``: fetches what a page would, then stops the command."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.fetched: dict[str, tuple[int, bytes, str]] = {}

    def __call__(self, url: str, *_: object, **__: object) -> bool:
        self.urls.append(url)

        def visit() -> None:
            try:
                self.fetched["page"] = get(url)
                self.fetched["asset"] = get(urljoin(url, "assets/page.js"))
                self.fetched["wasm"] = get(urljoin(url, "assets/engine.wasm"))
                self.fetched["mosaic"] = get(mosaic_url(url))
            finally:
                _thread.interrupt_main()

        threading.Thread(target=visit, daemon=True).start()
        return True


def snapshot(path: Path) -> tuple[str, int, list[str]]:
    beside = sorted(p.name for p in path.parent.iterdir())
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, beside


@pytest.mark.parametrize("name", OPENS)
def test_view_opens_the_page_with_the_mosaic_loaded_and_leaves_the_file_unchanged(
    name: str,
    tmp_path: Path,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "files" / name
    path.parent.mkdir()
    shutil.copyfile(READING / name, path)
    before = snapshot(path)
    browser = Browser()
    monkeypatch.setattr("webbrowser.open", browser)

    assert main(["view", str(path)]) == 0

    (url,) = browser.urls
    assert urlsplit(url).hostname == "127.0.0.1"
    out = capsys.readouterr().out
    assert url in out and str(path) in out
    status, body, kind = browser.fetched["page"]
    assert (status, body) == (200, (dist / "index.html").read_bytes()) and kind.startswith(
        "text/html"
    )
    assert browser.fetched["asset"][0] == 200
    assert browser.fetched["wasm"][2] == "application/wasm"
    status, body, _ = browser.fetched["mosaic"]
    assert (status, body) == (200, path.read_bytes())
    # The page names the file by the last part of the mosaic's address.
    assert mosaic_url(url).rsplit("/", 1)[1] == name
    assert snapshot(path) == before
    assert not any(path.with_name(path.name + s).exists() for s in SIDECARS)


def test_a_file_name_that_needs_quoting_reaches_the_page_whole(
    tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "my data & more #1 \uff5e.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", path)
    browser = Browser()
    monkeypatch.setattr("webbrowser.open", browser)
    assert main(["view", str(path)]) == 0
    (url,) = browser.urls
    assert browser.fetched["mosaic"][:2] == (200, path.read_bytes())
    assert unquote(mosaic_url(url).rsplit("/", 1)[1]) == path.name


@pytest.mark.parametrize("name", REFUSED)
def test_view_refuses_a_file_the_reading_rules_refuse_and_opens_no_page(
    name: str,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url))
    path = READING / name
    before = snapshot(path)
    assert main(["view", str(path)]) == 1
    assert opened == []
    err = capsys.readouterr().err
    assert err.startswith(f"mosaic view: {path}: ")
    with pytest.raises(Exception) as refused:
        view.checked_bytes(path)
    assert str(refused.value) in err
    assert snapshot(path) == before


def test_view_names_the_rule_a_file_breaks(dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    words = {
        "application-id.mosaic": "application_id",
        "user-version.mosaic": "user_version",
        "format-version.mosaic": "0.2",
        "newer-minor.mosaic": "format version",
        "node-changed.mosaic": "knowledge hash",
        "vector-changed.mosaic": "vector hash",
        "schema-extra-table.mosaic": "schema",
    }
    for name, word in words.items():
        assert main(["view", str(READING / name)]) == 1
        assert word in capsys.readouterr().err.lower(), name


def test_view_of_a_missing_file_is_an_error_naming_it(
    tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    missing = tmp_path / "nothing.mosaic"
    assert main(["view", str(missing)]) == 1
    assert capsys.readouterr().err == f"mosaic view: {missing}: no such file\n"
    assert main(["view", str(tmp_path)]) == 1
    assert "no such file" in capsys.readouterr().err


def test_view_without_a_built_viewer_says_how_to_build_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(view, "VIEWER_DIST", tmp_path / "no-dist")
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    assert main(["view", str(READING / "mosaic.mosaic")]) == 1
    assert "bun run build" in capsys.readouterr().err


def test_view_needs_a_file(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["view"])
    assert exit_info.value.code == 2


def test_the_server_hands_out_only_the_viewer_and_the_mosaic(dist: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("not yours", encoding="utf-8")
    data = (READING / "mosaic.mosaic").read_bytes()
    server, url = view.serve(view.viewer_dist(), "m.mosaic", data)
    try:
        root = f"http://127.0.0.1:{server.server_address[1]}"
        assert get(f"{root}/file/m.mosaic")[:2] == (200, data)
        for path in [
            "/file/other.mosaic",
            "/../secret.txt",
            "/%2e%2e/secret.txt",
            "/assets/../../secret.txt",
            "/assets/%2e%2e%2f%2e%2e%2fsecret.txt",
            "/assets",
            "/nothing",
        ]:
            assert get(root + path)[0] == 404, path
        post = urllib.request.Request(f"{root}/file/m.mosaic", data=b"x", method="POST")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(post, timeout=10)
        assert refused.value.code == 501
        assert get(url)[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_view_help_documents_the_command(tmp_path: Path) -> None:
    run = subprocess.run(
        [str(entry_point()), "view", "--help"], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0
    text = " ".join(run.stdout.split())
    for words in [
        "usage: mosaic view",
        "FILE",
        "reading rules",
        "section 3.8",
        "read-only",
        "127.0.0.1",
        "never written",
        "Ctrl-C",
        "exit status 1",
        "bun run build",
    ]:
        assert words in text, words
    listed = subprocess.run(
        [str(entry_point()), "--help"], capture_output=True, text=True, check=False
    ).stdout
    assert "open the viewer page" in listed


def test_view_runs_as_a_command_until_it_is_stopped(tmp_path: Path, dist: Path) -> None:
    """A process of its own, with a browser that records the address and fetches the file."""
    path = tmp_path / "m.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", path)
    before = snapshot(path)
    seen = tmp_path / "seen.json"
    browser = tmp_path / "browser.py"
    browser.write_text(
        "import json, sys, urllib.request\n"
        "from urllib.parse import parse_qs, unquote, urljoin, urlsplit\n"
        "url = sys.argv[1]\n"
        "named = urljoin(url, parse_qs(urlsplit(url).query)['mosaic'][0])\n"
        "page = urllib.request.urlopen(url).read()\n"
        "data = urllib.request.urlopen(named).read()\n"
        f"open({str(seen)!r}, 'w').write(json.dumps({{'url': url, 'page': len(page), "
        "'sha': __import__('hashlib').sha256(data).hexdigest()}))\n",
        encoding="utf-8",
    )
    env = {**os.environ, "BROWSER": f"{sys.executable} {browser} %s"}
    command = (
        "import sys; from mosaic_build import view; from mosaic_build.cli import main; "
        f"view.VIEWER_DIST = __import__('pathlib').Path({str(dist)!r}); "
        "sys.exit(main(sys.argv[1:]))"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", command, "view", str(path)],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not seen.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert seen.exists(), "the browser was not opened"
        got = json.loads(seen.read_text(encoding="utf-8"))
    finally:
        proc.send_signal(2)
        out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0
    assert got["url"] in out
    assert got["page"] > 0
    assert got["sha"] == before[0]
    assert snapshot(path)[0] == before[0] and snapshot(path)[1] == before[1]
