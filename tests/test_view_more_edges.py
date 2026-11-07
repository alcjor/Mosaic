"""More edge cases of ``mosaic view`` (M2.11), from docs/design.md (Viewer) and section 3.8.

Complements ``tests/test_view_edges.py``: files that are not regular files, sidecars already
beside the file, requests the page may make, and several views at once. A stand-in for the
built viewer is served.
"""

import _thread
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
from mosaic_build import view
from mosaic_build.cli import main

from tests.conftest import REPO

READING = REPO / "conformance" / "reading"


@pytest.fixture
def stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def mosaic_address(page: str) -> str:
    (named,) = parse_qs(urlsplit(page).query)["mosaic"]
    return urljoin(page, named)


def visit(
    path: Path | str, monkeypatch: pytest.MonkeyPatch, action: Callable[[str], Any]
) -> tuple[int, list[str], Any]:
    urls: list[str] = []
    box: dict[str, Any] = {}

    def browser(url: str, *_: object, **__: object) -> bool:
        urls.append(url)

        def work() -> None:
            try:
                box["result"] = action(url)
            except BaseException as e:
                box["error"] = e
            finally:
                _thread.interrupt_main()

        threading.Thread(target=work, daemon=True).start()
        return True

    monkeypatch.setattr("webbrowser.open", browser)
    code = main(["view", str(path)])
    if "error" in box:
        raise box["error"]
    return code, urls, box.get("result")


def read(url: str, method: str = "GET") -> tuple[int, bytes]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_a_device_that_is_not_a_mosaic_is_refused_naming_it(
    stand_in: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 3.8 step 2: a file that is not a conforming mosaic is refused, exit 1, no page.
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    assert main(["view", "/dev/null"]) == 1
    err = capsys.readouterr().err
    assert "/dev/null" in err and "Traceback" not in err


def test_a_dangling_symlink_is_a_missing_file(
    tmp_path: Path,
    stand_in: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 3.8 / design.md: a missing file is an error naming the file, exit 1, no page.
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    link = tmp_path / "dangling.mosaic"
    link.symlink_to(tmp_path / "gone.mosaic")
    assert main(["view", str(link)]) == 1
    err = capsys.readouterr().err
    assert str(link) in err and "Traceback" not in err


def test_an_empty_path_is_an_error_not_a_crash(
    stand_in: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    assert main(["view", ""]) == 1
    assert "Traceback" not in capsys.readouterr().err


def test_a_path_with_a_nul_is_an_error_not_a_crash(
    stand_in: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    assert main(["view", "a\0b.mosaic"]) == 1
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_file_is_an_error_naming_it(
    tmp_path: Path,
    stand_in: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    path = tmp_path / "locked.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", path)
    path.chmod(0)
    assert main(["view", str(path)]) == 1
    err = capsys.readouterr().err
    assert str(path) in err and "Traceback" not in err


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_a_sidecar_beside_the_file_refuses_it_and_nothing_is_written(
    suffix: str,
    tmp_path: Path,
    stand_in: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 3.1: a file has "no journal or write-ahead log beside it"; 3.8 step 1: read-only, so a
    # refusal must not recover, checkpoint or delete the sidecar either.
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    path = tmp_path / "m.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", path)
    side = tmp_path / ("m.mosaic" + suffix)
    side.write_bytes(b"not a real sidecar" * 50)
    before = (path.read_bytes(), side.read_bytes(), sorted(p.name for p in tmp_path.iterdir()))
    assert main(["view", str(path)]) == 1
    err = capsys.readouterr().err
    assert str(path) in err and "Traceback" not in err
    after = (path.read_bytes(), side.read_bytes(), sorted(p.name for p in tmp_path.iterdir()))
    assert after == before


def test_a_refused_file_leaves_its_directory_exactly_as_it_was(
    tmp_path: Path,
    stand_in: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 3.8 step 1 applies to a refused file too: refusing writes nothing.
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    for name in [
        "node-changed.mosaic",
        "vector-changed.mosaic",
        "user-version.mosaic",
        "not-sqlite.mosaic",
    ]:
        folder = tmp_path / name
        folder.mkdir()
        path = folder / name
        shutil.copyfile(READING / name, path)
        before = sorted(p.name for p in folder.iterdir())
        main(["view", str(path)])
        assert sorted(p.name for p in folder.iterdir()) == before, name


def test_the_page_address_does_not_depend_on_the_query_string_it_is_asked_with(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # design.md: the page is the viewer; the file travels in the address, not in a server query.
    shutil.copyfile(READING / "mosaic.mosaic", tmp_path / "m.mosaic")

    def probe(url: str) -> list[tuple[int, bytes]]:
        base = url.split("?", 1)[0]
        return [read(url), read(base), read(base + "?mosaic=other.mosaic"), read(url, "HEAD")]

    code, _, result = visit(tmp_path / "m.mosaic", monkeypatch, probe)
    assert code == 0
    page = (stand_in / "index.html").read_bytes()
    assert result[0] == (200, page)
    assert result[1] == (200, page)
    assert result[2][0] == 200
    assert result[3] == (200, b"") or result[3][0] in (200, 501)


def test_the_mosaic_can_be_read_by_a_head_request_without_a_body_or_not_at_all(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copyfile(READING / "mosaic.mosaic", tmp_path / "m.mosaic")
    code, _, result = visit(
        tmp_path / "m.mosaic", monkeypatch, lambda url: read(mosaic_address(url), "HEAD")
    )
    assert code == 0
    assert result[0] in (200, 405, 501)
    assert result[1] == b""


def test_two_servers_at_once_each_serve_their_own_file(
    tmp_path: Path, stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two commands may run together: addresses differ and each gives its own file.
    first = tmp_path / "first.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", first)
    other = (READING / "tessera.tessera").read_bytes()

    def second(url: str) -> tuple[str, bytes, bytes]:
        server, page = view.serve(view.viewer_dist(), "second.tessera", other)
        try:
            root = f"http://127.0.0.1:{server.server_address[1]}"
            assert page.startswith(root)
            return root, read(f"{root}/file/second.tessera")[1], read(mosaic_address(url))[1]
        finally:
            server.shutdown()
            server.server_close()

    code, urls, result = visit(first, monkeypatch, second)
    assert code == 0
    root, from_second, from_first = result
    assert not urls[0].startswith(root)
    assert (from_second, from_first) == (other, first.read_bytes())


def test_unknown_options_are_a_usage_error(stand_in: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["view", "--port", "1", str(READING / "mosaic.mosaic")])
    assert exit_info.value.code == 2
