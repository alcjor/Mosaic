"""``mosaic view FILE --view VIEW``: the page shaped by a view file, reloaded on save (plan M3.7).

docs/design.md, Implementation plan, "View file": "used by both view and export"; "mosaic view
watches it and reloads the page on save". The command reads the view file once before any page
opens: a wrong one is M3.5's error naming the file, the line and the setting, exit status 1, and
no page opens. While the page is open, the server hands it the file's current settings at
``view.json`` (``ViewSettings.as_json``), read again on each request, so a saved file reaches the
page without restarting the command; a file saved with an error answers that error, and the
page keeps what it shows.
"""

import _thread
import json
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import pytest
from mosaic_build import view, view_file
from mosaic_build.cli import main

from tests.conftest import REPO

MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"
VIEW = "types:\n  Item:\n    label: Thing\n"


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def fetch(url: str) -> tuple[int, bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def view_url(page: str) -> str:
    """The view file's settings' address, as the page resolves its ``?view=`` against its own."""
    (named,) = parse_qs(urlsplit(page).query)["view"]
    return urljoin(page, named)


def mosaic_copy(tmp_path: Path) -> Path:
    path = tmp_path / "files" / "mosaic.mosaic"
    path.parent.mkdir()
    shutil.copyfile(MOSAIC, path)
    return path


def test_help_documents_the_view_file(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        main(["view", "--help"])
    assert e.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "--view FILE" in text
    assert "view file" in text
    assert "reload" in text


def test_a_wrong_view_file_exits_1_with_its_error_and_opens_no_page(
    tmp_path: Path,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    served: list[object] = []
    monkeypatch.setattr(view, "serve", lambda *a, **k: served.append(a))
    bad = tmp_path / "view.yaml"
    bad.write_text("search: semantic\ntheme: sepia\n", encoding="utf-8")
    assert main(["view", str(mosaic_copy(tmp_path)), "--view", str(bad)]) == 1
    err = capsys.readouterr().err
    assert err.startswith(f"mosaic view: {bad}:2: view file: theme")
    assert opened == [] and served == []


def test_a_missing_view_file_exits_1_naming_it(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "absent.yaml"
    assert main(["view", str(mosaic_copy(tmp_path)), "--view", str(missing)]) == 1
    assert str(missing) in capsys.readouterr().err


class Browser:
    """Stands in for ``webbrowser.open``: runs ``visit`` on the address, then stops the command."""

    def __init__(self, visit: Callable[[str], object]) -> None:
        self.visit = visit
        self.urls: list[str] = []
        self.error: BaseException | None = None

    def __call__(self, url: str, *_: object, **__: object) -> bool:
        self.urls.append(url)

        def run() -> None:
            try:
                self.visit(url)
            except BaseException as e:  # reported by the test, after the command stops
                self.error = e
            finally:
                _thread.interrupt_main()

        threading.Thread(target=run, daemon=True).start()
        return True


def test_the_page_gets_the_current_settings_read_again_on_each_request(
    tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "view.yaml"
    path.write_text(VIEW, encoding="utf-8")
    seen: list[tuple[int, dict[str, object], str]] = []

    def visit(url: str) -> None:
        def settings() -> tuple[int, dict[str, object], str]:
            status, body, kind = fetch(view_url(url))
            return status, json.loads(body), kind

        seen.append(settings())
        path.write_text("search: text\n", encoding="utf-8")
        seen.append(settings())
        path.write_text("search: fuzzy\n", encoding="utf-8")
        seen.append(settings())
        path.write_text(VIEW, encoding="utf-8")
        seen.append(settings())

    browser = Browser(visit)
    monkeypatch.setattr("webbrowser.open", browser)
    before = path.read_bytes()
    assert main(["view", str(mosaic_copy(tmp_path)), "--view", str(path)]) == 0
    assert browser.error is None, browser.error
    first, second, broken, fixed = seen
    assert first == (200, view_file.read(path).as_json(), "application/json")
    assert second[0] == 200 and second[1]["search"] == "text"
    status, body, _ = broken
    assert status == 422
    message = f"{path}:1: view file: search must be one of semantic, text, not 'fuzzy'"
    assert body == {"error": message}
    assert fixed == first
    assert path.read_bytes() == before  # the command never writes the view file


def test_without_a_view_file_the_page_is_named_none(
    tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    got: list[tuple[int, bytes, str]] = []
    browser = Browser(lambda url: got.append(fetch(urljoin(url, "view.json"))))
    monkeypatch.setattr("webbrowser.open", browser)
    assert main(["view", str(mosaic_copy(tmp_path))]) == 0
    (url,) = browser.urls
    assert "view" not in parse_qs(urlsplit(url).query)
    assert got[0][0] == 404


def test_the_address_names_the_settings_beside_the_mosaic_and_the_model() -> None:
    url = view.page_url(8000, "a.mosaic", model=True, view=True)
    query = parse_qs(urlsplit(url).query)
    assert query["mosaic"] == ["file/a.mosaic"]
    assert query["model"] == ["model/"]
    assert query["view"] == ["view.json"]
    assert "view" not in parse_qs(urlsplit(view.page_url(8000, "a.mosaic")).query)
