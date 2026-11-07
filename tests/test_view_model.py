"""``mosaic view --model DIR`` gives the page the model of section 6 (M2.12, answer A on #117).

The model reaches the page at runtime from the directory given to ``mosaic view``, checked by
its pinned hashes (section 6), never bundled into the viewer build. With it, the page embeds
queries and ``find`` lists vector matches; without it, the page opens and searches by names and
full text only (section 3.8). A directory whose files are not the pinned ones is an error
naming the file and both hashes, with exit status 1, and no page opens.

These tests pin a stand-in model of two small files (the real one is 23 MB), so the checks run
fast; ``tests/fixtures/test_netflix_read.py`` (slow) gives the real model to the real viewer.
"""

import _thread
import hashlib
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import pytest
from mosaic_build import view
from mosaic_build.cli import main
from mosaic_build.mosaic.vectors import MODEL, Model, PinnedFile

from tests.conftest import REPO
from tests.test_cli import entry_point
from tests.test_view import get, mosaic_url, snapshot

READING_MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"
FILES = {"onnx/model_quantized.onnx": b"stand-in model bytes", "tokenizer.json": b'{"model":{}}'}


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the built viewer: one page."""
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A model directory whose two files are the pinned ones of a stand-in model."""
    directory = tmp_path / "model"
    for path, data in FILES.items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_bytes(data)
    (directory / "README.md").write_text("not a pinned file", encoding="utf-8")
    pinned = Model(
        name=MODEL.name,
        repository=MODEL.repository,
        revision=MODEL.revision,
        licence=MODEL.licence,
        files=tuple(PinnedFile(path, _sha(data)) for path, data in FILES.items()),
    )
    monkeypatch.setattr(view, "MODEL", pinned)
    return directory


def model_url(page: str) -> str | None:
    """The model's address, as the page resolves its ``?model=`` against its own, or None."""
    named = parse_qs(urlsplit(page).query).get("model")
    return None if named is None else urljoin(page, named[0])


class Browser:
    """Stands in for ``webbrowser.open``: fetches the model files, then stops the command."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.fetched: dict[str, tuple[int, bytes, str]] = {}

    def __call__(self, url: str, *_: object, **__: object) -> bool:
        self.urls.append(url)

        def visit() -> None:
            try:
                self.fetched["mosaic"] = get(mosaic_url(url))
                base = model_url(url) or urljoin(url, "model/")
                for path in [*FILES, "README.md", "../file/x", "onnx"]:
                    self.fetched[path] = get(urljoin(base, path))
            finally:
                _thread.interrupt_main()

        threading.Thread(target=visit, daemon=True).start()
        return True


def test_view_with_a_model_gives_the_page_the_pinned_files(
    tmp_path: Path, dist: Path, model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "m.mosaic"
    shutil.copyfile(READING_MOSAIC, path)
    files_before = {p: snapshot(model / p) for p in FILES}
    browser = Browser()
    monkeypatch.setattr("webbrowser.open", browser)

    assert main(["view", str(path), "--model", str(model)]) == 0

    (url,) = browser.urls
    assert model_url(url) is not None
    assert browser.fetched["mosaic"][:2] == (200, path.read_bytes())
    for p, data in FILES.items():
        assert browser.fetched[p][:2] == (200, data), p
    # Only the pinned files of the directory reach the page.
    for p in ["README.md", "onnx"]:
        assert browser.fetched[p][0] == 404, p
    assert {p: snapshot(model / p) for p in FILES} == files_before


def test_view_without_a_model_opens_the_page_with_no_model(
    tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = Browser()
    monkeypatch.setattr("webbrowser.open", browser)
    assert main(["view", str(READING_MOSAIC)]) == 0
    (url,) = browser.urls
    assert model_url(url) is None
    assert browser.fetched["mosaic"][0] == 200
    for p in FILES:
        assert browser.fetched[p][0] == 404, p


@pytest.mark.parametrize("changed", sorted(FILES))
def test_a_model_file_with_another_hash_is_an_error_naming_the_file_and_both_hashes(
    changed: str,
    dist: Path,
    model: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    other = b"other bytes"
    (model / changed).write_bytes(other)
    assert main(["view", str(READING_MOSAIC), "--model", str(model)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("mosaic view: ")
    assert changed in err
    assert _sha(other) in err and _sha(FILES[changed]) in err
    assert (model / changed).read_bytes() == other


@pytest.mark.parametrize("missing", sorted(FILES))
def test_a_model_directory_without_a_pinned_file_is_an_error_naming_it(
    missing: str,
    dist: Path,
    model: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    (model / missing).unlink()
    assert main(["view", str(READING_MOSAIC), "--model", str(model)]) == 1
    assert missing in capsys.readouterr().err


def test_a_model_that_is_no_directory_is_an_error_naming_it(
    tmp_path: Path,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    nothing = tmp_path / "no-model"
    assert main(["view", str(READING_MOSAIC), "--model", str(nothing)]) == 1
    assert str(nothing) in capsys.readouterr().err


def test_a_refused_mosaic_is_refused_before_the_model_is_read(
    dist: Path,
    model: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    refused = READING_MOSAIC.with_name("application-id.mosaic")
    assert main(["view", str(refused), "--model", str(model)]) == 1
    assert "application_id" in capsys.readouterr().err


def test_the_served_model_is_the_bytes_that_were_checked(dist: Path, model: Path) -> None:
    files = view.checked_model(model)
    assert files == FILES
    data = READING_MOSAIC.read_bytes()
    server, url = view.serve(view.viewer_dist(), "m.mosaic", data, model=files)
    try:
        # A change to the directory after the check never reaches the page.
        (model / "tokenizer.json").write_bytes(b"changed afterwards")
        base = model_url(url)
        assert base is not None
        assert get(urljoin(base, "tokenizer.json"))[:2] == (200, FILES["tokenizer.json"])
        post = urllib.request.Request(urljoin(base, "tokenizer.json"), data=b"x", method="POST")
        with pytest.raises(urllib.error.HTTPError) as no:
            urllib.request.urlopen(post, timeout=10)
        assert no.value.code == 501
    finally:
        server.shutdown()
        server.server_close()


def test_view_help_documents_the_model() -> None:
    run = subprocess.run(
        [str(entry_point()), "view", "--help"], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0
    text = " ".join(run.stdout.split())
    for words in ["--model DIR", "section 6", "pinned", "names and full text"]:
        assert words in text, words
