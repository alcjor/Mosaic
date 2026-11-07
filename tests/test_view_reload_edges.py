"""Edge cases of ``mosaic view FILE --view VIEW`` (plan M3.7), from the words of docs/design.md
("View file": "mosaic view watches it and reloads the page on save"), the command's own
``--help`` (a wrong view file is an error naming the file, the line and the setting, exit status
1, no page opens; a file saved with an error keeps the page as it was and shows the error; the
view file is only read) and the maintainer's answers on #120 (every key optional, so an empty
view file gives M2's viewer; types appear in the order the file writes them)."""

import _thread
import json
import os
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import pytest
from mosaic_build import view, view_file
from mosaic_build.cli import main

from tests.conftest import REPO

MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


@pytest.fixture
def mosaic(tmp_path: Path) -> Path:
    path = tmp_path / "files" / "mosaic.mosaic"
    path.parent.mkdir()
    shutil.copyfile(MOSAIC, path)
    return path


def get(url: str, method: str = "GET", data: bytes | None = None) -> tuple[int, bytes, Any]:
    request = urllib.request.Request(url, method=method, data=data)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def settings_url(page: str) -> str:
    (named,) = parse_qs(urlsplit(page).query)["view"]
    return urljoin(page, named)


def run_view(
    args: list[str], monkeypatch: pytest.MonkeyPatch, action: Callable[[str], Any]
) -> tuple[int, list[str], Any]:
    """Run ``mosaic view ARGS``; ``action`` gets the page address, then the command is stopped."""
    urls: list[str] = []
    box: dict[str, Any] = {}

    def browser(url: str, *_: object, **__: object) -> bool:
        urls.append(url)

        def work() -> None:
            try:
                box["result"] = action(url)
            except BaseException as e:  # reported by the test, after the command stops
                box["error"] = e
            finally:
                _thread.interrupt_main()

        threading.Thread(target=work, daemon=True).start()
        return True

    monkeypatch.setattr("webbrowser.open", browser)
    code = main(["view", *args])
    if "error" in box:
        raise box["error"]
    return code, urls, box.get("result")


def refused(
    args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    """Run a command that must exit 1 with no page; return its stderr."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    served: list[object] = []
    monkeypatch.setattr(view, "serve", lambda *a, **k: served.append(a))
    assert main(["view", *args]) == 1
    assert opened == [] and served == []
    return capsys.readouterr().err


# A wrong view file: exit 1, the file named, no page.


@pytest.mark.parametrize(
    ("text", "line", "setting"),
    [
        ("search: fuzzy\n", 1, "search"),
        ("# c\n\n\ntheme: sepia\n", 4, "theme"),
        ("types:\n  A:\n    colour: red\n", 3, "colour"),
        ("colour: red\n", 1, "colour"),
        ("types:\n  A: {}\n  A: {}\n", 3, "A"),
    ],
)
def test_wrong_view_file_names_file_line_and_setting(
    text: str,
    line: int,
    setting: str,
    tmp_path: Path,
    dist: Path,
    mosaic: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "v.yaml"
    bad.write_text(text, encoding="utf-8")
    err = refused([str(mosaic), "--view", str(bad)], monkeypatch, capsys)
    assert f"{bad}:{line}:" in err
    assert setting in err


def test_view_file_error_is_the_reader_error_verbatim(
    tmp_path: Path,
    dist: Path,
    mosaic: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The error is M3.5's: the command adds only its own name in front."""
    bad = tmp_path / "v.yaml"
    bad.write_text("search: fuzzy\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        view_file.read(bad)
    err = refused([str(mosaic), "--view", str(bad)], monkeypatch, capsys)
    assert str(e.value) in err


def test_view_file_that_is_a_directory_is_an_error_naming_it(
    tmp_path: Path,
    dist: Path,
    mosaic: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "v.yaml"
    directory.mkdir()
    assert str(directory) in refused([str(mosaic), "--view", str(directory)], monkeypatch, capsys)


@pytest.mark.parametrize("content", [b"\xff\xfe\x00bad", b"search: text\n\x00\n", b"{{{"])
def test_corrupt_view_file_is_an_error_naming_it_not_a_crash(
    content: bytes,
    tmp_path: Path,
    dist: Path,
    mosaic: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "v.yaml"
    bad.write_bytes(content)
    err = refused([str(mosaic), "--view", str(bad)], monkeypatch, capsys)
    assert str(bad) in err
    assert "Traceback" not in err


def test_empty_path_for_the_view_file_is_an_error_not_a_crash(
    dist: Path,
    mosaic: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = refused([str(mosaic), "--view", ""], monkeypatch, capsys)
    assert "Traceback" not in err


def test_view_flag_without_a_value_is_a_usage_error(mosaic: Path, dist: Path) -> None:
    with pytest.raises(SystemExit) as e:
        main(["view", str(mosaic), "--view"])
    assert e.value.code == 2


def test_wrong_view_file_does_not_hide_a_bad_mosaic_name(
    tmp_path: Path,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both wrong: still exit 1, no page, and an error that names a file."""
    bad = tmp_path / "v.yaml"
    bad.write_text("search: fuzzy\n", encoding="utf-8")
    missing = tmp_path / "absent.mosaic"
    err = refused([str(missing), "--view", str(bad)], monkeypatch, capsys)
    assert str(missing) in err or str(bad) in err


def test_wrong_view_file_with_a_bad_model_dir_is_still_exit_1_no_page(
    tmp_path: Path,
    dist: Path,
    mosaic: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "v.yaml"
    bad.write_text("theme: sepia\n", encoding="utf-8")
    err = refused(
        [str(mosaic), "--model", str(tmp_path / "nomodel"), "--view", str(bad)],
        monkeypatch,
        capsys,
    )
    assert err.strip() != ""


# A right view file: the page is shaped by it.


def test_empty_view_file_gives_the_defaults_and_opens_the_page(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answer on #120: every key is optional, so an empty view file gives M2's viewer."""
    path = tmp_path / "empty.yaml"
    path.write_bytes(b"")
    code, urls, got = run_view(
        [str(mosaic), "--view", str(path)], monkeypatch, lambda u: get(settings_url(u))
    )
    assert code == 0 and len(urls) == 1
    status, body, _ = got
    assert status == 200
    assert json.loads(body) == view_file.read(path).as_json()
    assert json.loads(body)["search"] == "semantic"


def test_comment_only_view_file_is_the_same_as_an_empty_one(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("# nothing here\n", encoding="utf-8")
    empty = tmp_path / "e.yaml"
    empty.write_bytes(b"")
    code, _, got = run_view(
        [str(mosaic), "--view", str(path)], monkeypatch, lambda u: get(settings_url(u))
    )
    assert code == 0
    assert json.loads(got[1]) == view_file.read(empty).as_json()


def test_view_file_path_with_spaces_and_non_ascii_is_served(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "vue été.yaml"
    path.write_text("search: text\n", encoding="utf-8")
    code, _, got = run_view(
        [str(mosaic), "--view", str(path)], monkeypatch, lambda u: get(settings_url(u))
    )
    assert code == 0 and got[0] == 200
    assert json.loads(got[1])["search"] == "text"


def test_view_equals_form_is_accepted(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: text\n", encoding="utf-8")
    code, _, got = run_view(
        [str(mosaic), f"--view={path}"], monkeypatch, lambda u: get(settings_url(u))
    )
    assert code == 0 and json.loads(got[1])["search"] == "text"


def test_types_come_in_the_order_the_file_writes_them_and_unicode_survives(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answer on #120: types appear in the order the file writes them."""
    path = tmp_path / "v.yaml"
    path.write_text(
        "types:\n  Zed:\n    label: Zèbre ✓\n  Alpha: {}\n  Mid: {}\n", encoding="utf-8"
    )
    code, _, got = run_view(
        [str(mosaic), "--view", str(path)], monkeypatch, lambda u: get(settings_url(u))
    )
    assert code == 0
    text = got[1].decode("utf-8")
    assert text.index("Zed") < text.index("Alpha") < text.index("Mid")
    assert "Zèbre ✓" in text or "Z\\u00e8bre" in text
    assert "Zèbre ✓" in json.dumps(json.loads(text), ensure_ascii=False)


def test_the_settings_are_the_same_bytes_when_asked_twice(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("types:\n  B: {}\n  A: {}\n", encoding="utf-8")

    def twice(page: str) -> tuple[bytes, bytes]:
        return get(settings_url(page))[1], get(settings_url(page))[1]

    _, _, got = run_view([str(mosaic), "--view", str(path)], monkeypatch, twice)
    assert got[0] == got[1]


# While the page is open.


def test_an_editor_that_saves_by_renaming_a_new_file_over_it_is_seen(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: semantic\n", encoding="utf-8")

    def visit(page: str) -> list[Any]:
        seen = [json.loads(get(settings_url(page))[1])["search"]]
        temp = tmp_path / "v.yaml.swp"
        temp.write_text("search: text\n", encoding="utf-8")
        os.replace(temp, path)
        seen.append(json.loads(get(settings_url(page))[1])["search"])
        return seen

    code, _, got = run_view([str(mosaic), "--view", str(path)], monkeypatch, visit)
    assert code == 0 and got == ["semantic", "text"]


def test_a_view_file_that_is_a_symlink_follows_its_target(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.yaml"
    target.write_text("search: semantic\n", encoding="utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(target)

    def visit(page: str) -> list[Any]:
        seen = [json.loads(get(settings_url(page))[1])["search"]]
        target.write_text("search: text\n", encoding="utf-8")
        seen.append(json.loads(get(settings_url(page))[1])["search"])
        return seen

    code, _, got = run_view([str(mosaic), "--view", str(link)], monkeypatch, visit)
    assert code == 0 and got == ["semantic", "text"]


def test_saving_an_empty_file_while_open_gives_defaults_not_an_error(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: text\ntheme: dark\n", encoding="utf-8")

    def visit(page: str) -> tuple[int, dict[str, Any]]:
        path.write_bytes(b"")
        status, body, _ = get(settings_url(page))
        return status, json.loads(body)

    code, _, (status, body) = run_view([str(mosaic), "--view", str(path)], monkeypatch, visit)
    assert code == 0 and status == 200
    assert body["search"] == "semantic" and body["theme"] == "auto"


def test_a_file_saved_with_each_kind_of_error_answers_an_error_and_the_server_lives_on(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: text\n", encoding="utf-8")
    broken = [b"search: fuzzy\n", b"\xff\xfe\x00", b"{{{", b"search: text\nsearch: text\n"]

    def visit(page: str) -> list[tuple[int, dict[str, Any]]]:
        out = []
        for content in broken:
            path.write_bytes(content)
            status, body, _ = get(settings_url(page))
            out.append((status, json.loads(body)))
        path.write_text("search: text\n", encoding="utf-8")
        status, body, _ = get(settings_url(page))
        out.append((status, json.loads(body)))
        # the mosaic is still served after all that
        (named,) = parse_qs(urlsplit(page).query)["mosaic"]
        assert get(urljoin(page, named))[0] == 200
        return out

    code, _, got = run_view([str(mosaic), "--view", str(path)], monkeypatch, visit)
    assert code == 0
    for status, body in got[:-1]:
        assert status == 422
        assert str(path) in body["error"]
    assert got[-1][0] == 200 and got[-1][1]["search"] == "text"


def test_a_view_file_removed_while_open_is_an_error_naming_it_not_the_old_settings(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: text\n", encoding="utf-8")

    def visit(page: str) -> tuple[int, bytes]:
        path.unlink()
        status, body, _ = get(settings_url(page))
        # restored: served again
        path.write_text("search: text\n", encoding="utf-8")
        assert get(settings_url(page))[0] == 200
        return status, body

    code, _, (status, body) = run_view([str(mosaic), "--view", str(path)], monkeypatch, visit)
    assert code == 0
    assert status >= 400 and str(path) in body.decode("utf-8", "replace")


def test_the_settings_address_ignores_a_query_string(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: text\n", encoding="utf-8")
    code, _, got = run_view(
        [str(mosaic), "--view", str(path)],
        monkeypatch,
        lambda u: (get(settings_url(u))[1], get(settings_url(u) + "?t=123")[1]),
    )
    assert code == 0 and got[0] == got[1]


def test_the_server_never_writes_through_the_settings_address(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: text\n", encoding="utf-8")
    before = path.read_bytes()

    def visit(page: str) -> list[int]:
        url = settings_url(page)
        return [
            get(url, "POST", b"search: semantic\n")[0],
            get(url, "PUT", b"search: semantic\n")[0],
            get(url, "DELETE")[0],
        ]

    code, _, got = run_view([str(mosaic), "--view", str(path)], monkeypatch, visit)
    assert code == 0
    assert all(s >= 400 for s in got)
    assert path.read_bytes() == before


def test_the_view_file_itself_is_not_served_as_a_file(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("search: text\n# secret-comment\n", encoding="utf-8")

    def visit(page: str) -> list[int]:
        return [
            get(urljoin(page, "v.yaml"))[0],
            get(urljoin(page, "file/v.yaml"))[0],
            get(urljoin(page, "view.yaml"))[0],
            get(urljoin(page, "file/../v.yaml"))[0],
        ]

    code, _, got = run_view([str(mosaic), "--view", str(path)], monkeypatch, visit)
    assert code == 0
    assert all(s != 200 for s in got)


def test_the_view_file_and_its_directory_are_unchanged_after_the_command(
    tmp_path: Path, dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "views"
    folder.mkdir()
    path = folder / "v.yaml"
    path.write_text("search: text\n", encoding="utf-8")
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    before = (path.read_bytes(), path.stat().st_mtime_ns, sorted(os.listdir(folder)))

    def visit(page: str) -> int:
        return get(settings_url(page))[0]

    code, _, _ = run_view([str(mosaic), "--view", str(path)], monkeypatch, visit)
    assert code == 0
    assert (path.read_bytes(), path.stat().st_mtime_ns, sorted(os.listdir(folder))) == before


def test_a_refused_view_file_leaves_its_directory_as_it_was(
    tmp_path: Path,
    dist: Path,
    mosaic: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = tmp_path / "views"
    folder.mkdir()
    path = folder / "v.yaml"
    path.write_text("search: fuzzy\n", encoding="utf-8")
    before = (path.read_bytes(), sorted(os.listdir(folder)))
    refused([str(mosaic), "--view", str(path)], monkeypatch, capsys)
    assert (path.read_bytes(), sorted(os.listdir(folder))) == before


def test_without_a_view_file_the_page_address_has_no_view_and_help_still_works(
    dist: Path, mosaic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, urls, got = run_view(
        [str(mosaic)], monkeypatch, lambda u: get(urljoin(u, "view.json"))[0]
    )
    assert code == 0 and got == 404
    assert "view" not in parse_qs(urlsplit(urls[0]).query)
