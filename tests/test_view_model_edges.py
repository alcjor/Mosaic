"""Edge cases of ``mosaic view --model DIR`` (M2.12, answer A on #117), from the spec's words.

The model reaches the page at runtime from the directory given to ``mosaic view``, each file
checked by its pinned SHA-256 (section 6), never bundled into the viewer build. The reading rules
(section 3.8) bind the mosaic the same way with or without a model; an unsupported or absent model
only changes how the page searches. Written without reading the implementation: a stand-in for
the built viewer is served, and a stand-in model of two small files is pinned.
"""

import _thread
import hashlib
import http.client
import json
import os
import subprocess
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
from mosaic_build.mosaic.vectors import MODEL, Model, PinnedFile

from tests.conftest import REPO
from tests.test_cli import entry_point

READING = REPO / "conformance" / "reading"
CASES = json.loads((READING / "cases.json").read_text(encoding="utf-8"))
REFUSED = sorted(name for name, case in CASES.items() if not case["opens"])
OPENS = sorted(name for name, case in CASES.items() if case["opens"])
FILES = {"onnx/model_quantized.onnx": b"stand-in model bytes", "tokenizer.json": b'{"model":{}}'}
README = b"not a pinned file, and secret"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>viewer</title>", encoding="utf-8")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


@pytest.fixture
def model(tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory whose two files are the pinned ones of a stand-in model, plus a bystander."""
    directory = tmp_path / "model"
    for path, data in FILES.items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_bytes(data)
    (directory / "README.md").write_bytes(README)
    pinned = Model(
        name=MODEL.name,
        repository=MODEL.repository,
        revision=MODEL.revision,
        licence=MODEL.licence,
        files=tuple(PinnedFile(path, sha(data)) for path, data in FILES.items()),
    )
    monkeypatch.setattr(view, "MODEL", pinned)
    return directory


def tree(directory: Path) -> dict[str, tuple[bytes | None, int]]:
    """Every entry under ``directory`` with its bytes (None for a directory) and mtime."""
    found: dict[str, tuple[bytes | None, int]] = {}
    for p in sorted(directory.rglob("*")):
        key = p.relative_to(directory).as_posix()
        found[key] = (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
    return found


def model_base(page: str) -> str:
    (named,) = parse_qs(urlsplit(page).query)["model"]
    return urljoin(page, named)


class Visitor:
    """A browser stand-in: runs ``action(url)`` on a thread, then stops the command."""

    def __init__(self, action: Callable[[str], Any]) -> None:
        self.action = action
        self.urls: list[str] = []
        self.result: Any = None
        self.error: BaseException | None = None

    def __call__(self, url: str, *_: object, **__: object) -> bool:
        self.urls.append(url)

        def go() -> None:
            try:
                self.result = self.action(url)
            except BaseException as e:
                self.error = e
            finally:
                _thread.interrupt_main()

        threading.Thread(target=go, daemon=True).start()
        return True


def view_with(
    args: list[str], monkeypatch: pytest.MonkeyPatch, action: Callable[[str], Any]
) -> tuple[int, Visitor]:
    visitor = Visitor(action)
    monkeypatch.setattr("webbrowser.open", visitor)
    code = main(["view", *args])
    if visitor.error:
        raise visitor.error
    return code, visitor


def no_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))


def raw(url: str, path: str, method: str = "GET") -> tuple[int, bytes, dict[str, str]]:
    """A request whose path is sent exactly as given, so no client tidies it first."""
    parts = urlsplit(url)
    assert parts.hostname is not None
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    try:
        connection.putrequest(method, path, skip_accept_encoding=True)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


# --- the model directory itself ---------------------------------------------------------------


def test_a_model_that_is_a_file_not_a_directory_is_an_error_naming_it(
    tmp_path: Path, model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    file = tmp_path / "model-is-a-file"
    file.write_bytes(b"x")
    assert main(["view", str(READING / "mosaic.mosaic"), "--model", str(file)]) == 1
    err = capsys.readouterr().err
    assert str(file) in err and "Traceback" not in err


def test_a_pinned_file_that_is_a_directory_is_an_error_naming_it(
    model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    (model / "tokenizer.json").unlink()
    (model / "tokenizer.json").mkdir()
    assert main(["view", str(READING / "mosaic.mosaic"), "--model", str(model)]) == 1
    err = capsys.readouterr().err
    assert "tokenizer.json" in err and "Traceback" not in err


def test_an_empty_pinned_file_is_a_hash_error_naming_the_file_and_both_hashes(
    model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    (model / "tokenizer.json").write_bytes(b"")
    assert main(["view", str(READING / "mosaic.mosaic"), "--model", str(model)]) == 1
    err = capsys.readouterr().err
    assert "tokenizer.json" in err
    assert sha(b"") in err and sha(FILES["tokenizer.json"]) in err


def test_a_pinned_file_with_one_byte_appended_is_refused(
    model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    changed = FILES["onnx/model_quantized.onnx"] + b"\n"
    (model / "onnx" / "model_quantized.onnx").write_bytes(changed)
    assert main(["view", str(READING / "mosaic.mosaic"), "--model", str(model)]) == 1
    err = capsys.readouterr().err
    assert sha(changed) in err and sha(FILES["onnx/model_quantized.onnx"]) in err


def test_the_files_of_another_model_directory_name_are_looked_up_by_pinned_path_not_by_name(
    model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The right bytes under the wrong path are no model: the file is missing at its path."""
    no_page(monkeypatch)
    (model / "tokenizer.json").rename(model / "Tokenizer.json.bak")
    assert main(["view", str(READING / "mosaic.mosaic"), "--model", str(model)]) == 1
    assert "tokenizer.json" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "\0"])
def test_an_empty_or_nul_model_argument_is_an_error_not_a_crash(
    value: str,
    model: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_page(monkeypatch)
    try:
        code = main(["view", str(READING / "mosaic.mosaic"), "--model", value])
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    assert code in (1, 2)
    assert "Traceback" not in capsys.readouterr().err


def test_model_needs_a_value(
    model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    with pytest.raises(SystemExit) as stop:
        main(["view", str(READING / "mosaic.mosaic"), "--model"])
    assert stop.value.code == 2
    assert "--model" in capsys.readouterr().err


def test_a_relative_model_path_and_a_trailing_slash_open_the_same_model(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def read_files(page: str) -> dict[str, bytes]:
        base = model_base(page)
        return {p: urllib.request.urlopen(urljoin(base, p), timeout=10).read() for p in FILES}

    monkeypatch.chdir(model.parent)
    for given in ["model", "model/", "./model", str(model) + "/"]:
        code, visitor = view_with(
            [str(READING / "mosaic.mosaic"), "--model", given], monkeypatch, read_files
        )
        assert code == 0, given
        assert visitor.result == FILES, given


def test_a_symlinked_model_directory_and_symlinked_files_are_checked_and_served(
    tmp_path: Path, model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = tmp_path / "link"
    link.symlink_to(model, target_is_directory=True)

    def read_files(page: str) -> dict[str, bytes]:
        base = model_base(page)
        return {p: urllib.request.urlopen(urljoin(base, p), timeout=10).read() for p in FILES}

    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(link)], monkeypatch, read_files
    )
    assert code == 0 and visitor.result == FILES


def test_a_model_given_with_a_tessera_opens_it_too(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, visitor = view_with(
        [str(READING / "tessera.tessera"), "--model", str(model)],
        monkeypatch,
        lambda page: urllib.request.urlopen(urljoin(model_base(page), "tokenizer.json")).read(),
    )
    assert code == 0 and visitor.result == FILES["tokenizer.json"]


def test_the_model_directory_is_left_exactly_as_it_was(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = tree(model)
    code, _ = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)],
        monkeypatch,
        lambda page: urllib.request.urlopen(urljoin(model_base(page), "tokenizer.json")).read(),
    )
    assert code == 0
    assert tree(model) == before


def test_a_model_error_leaves_the_directory_and_the_mosaic_exactly_as_they_were(
    tmp_path: Path, model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_page(monkeypatch)
    (model / "tokenizer.json").write_bytes(b"other")
    before = tree(model)
    mosaic = tmp_path / "m.mosaic"
    mosaic.write_bytes((READING / "mosaic.mosaic").read_bytes())
    mosaic_before = (mosaic.read_bytes(), mosaic.stat().st_mtime_ns)
    assert main(["view", str(mosaic), "--model", str(model)]) == 1
    assert tree(model) == before
    assert (mosaic.read_bytes(), mosaic.stat().st_mtime_ns) == mosaic_before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dist", "m.mosaic", "model"]


def test_a_model_error_prints_nothing_on_stdout(
    model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    (model / "tokenizer.json").write_bytes(b"other")
    assert main(["view", str(READING / "mosaic.mosaic"), "--model", str(model)]) == 1
    assert capsys.readouterr().out == ""


# --- the model never loosens the reading rules (section 3.8) ----------------------------------


@pytest.mark.parametrize("name", REFUSED)
def test_a_file_the_reading_rules_refuse_is_refused_with_a_model_too(
    name: str,
    model: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_page(monkeypatch)
    assert main(["view", str(READING / name), "--model", str(model)]) == 1
    err = capsys.readouterr().err
    assert name in err and "Traceback" not in err


@pytest.mark.parametrize("name", OPENS)
def test_a_file_the_reading_rules_accept_opens_with_a_model_of_another_vector_model(
    name: str, model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 3.8: a reader that does not support the file's embedding model still opens it."""
    code, visitor = view_with(
        [str(READING / name), "--model", str(model)], monkeypatch, lambda _: 0
    )
    assert code == 0 and len(visitor.urls) == 1


def test_a_missing_mosaic_is_an_error_naming_it_even_with_a_good_model(
    tmp_path: Path, model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    missing = tmp_path / "nothing.mosaic"
    assert main(["view", str(missing), "--model", str(model)]) == 1
    assert str(missing) in capsys.readouterr().err


def test_a_changed_vector_is_refused_naming_the_vector_hash_with_a_good_model(
    model: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_page(monkeypatch)
    assert main(["view", str(READING / "vector-changed.mosaic"), "--model", str(model)]) == 1
    assert "vector" in capsys.readouterr().err


# --- what the server hands out (section 10: nothing beyond the pinned files) ------------------


def test_the_model_files_are_served_with_their_exact_length_and_repeat_the_same(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def read(page: str) -> list[Any]:
        base = model_base(page)
        out = []
        for p in FILES:
            first = raw(base, urlsplit(urljoin(base, p)).path)
            second = raw(base, urlsplit(urljoin(base, p)).path)
            out.append((p, first[:2], second[:2], first[2].get("Content-Length")))
        return out

    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, read
    )
    assert code == 0
    for p, first, second, length in visitor.result:
        assert first == (200, FILES[p]) and second == first
        assert length == str(len(FILES[p]))


@pytest.mark.parametrize(
    "tail",
    [
        "README.md",
        "onnx",
        "onnx/",
        "tokenizer.json/",
        "tokenizer.json/extra",
        "onnx/../README.md",
        "%2e%2e/README.md",
        "..%2fREADME.md",
        "onnx/..%2fREADME.md",
        "%2e%2e%2f%2e%2e%2fmodel%2fREADME.md",
        "..\\README.md",
        "onnx\\..\\README.md",
        "tokenizer.json%00.md",
        "TOKENIZER.JSON",
        "onnx/MODEL_QUANTIZED.ONNX",
        "tokenizer.json.bak",
    ],
)
def test_nothing_but_the_pinned_files_is_served_under_the_model_address(
    tail: str, model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (model / "tokenizer.json.bak").write_bytes(README)

    def ask(page: str) -> tuple[int, bytes]:
        base = model_base(page)
        status, body, _ = raw(base, urlsplit(base).path + tail)
        return status, body

    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, ask
    )
    assert code == 0
    status, body = visitor.result
    assert README not in body and b"secret" not in body
    assert not (status == 200 and body in FILES.values()), "a pinned file under another name"
    assert 400 <= status < 500, status


def test_a_query_string_or_fragment_style_suffix_on_a_model_file_still_serves_that_file(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def ask(page: str) -> tuple[int, bytes]:
        base = model_base(page)
        status, body, _ = raw(base, urlsplit(base).path + "tokenizer.json?x=1&y=2")
        return status, body

    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, ask
    )
    assert code == 0
    assert visitor.result == (200, FILES["tokenizer.json"])


def test_the_model_is_read_only_over_http(model: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def ask(page: str) -> list[int]:
        base = model_base(page)
        codes = []
        for method in ["POST", "PUT", "DELETE", "PATCH"]:
            codes.append(raw(base, urlsplit(base).path + "tokenizer.json", method)[0])
        return codes

    before = tree(model)
    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, ask
    )
    assert code == 0
    assert all(400 <= c < 600 for c in visitor.result), visitor.result
    assert tree(model) == before


def test_the_mosaic_address_never_serves_the_model_directory(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def ask(page: str) -> list[int]:
        origin = f"{urlsplit(page).scheme}://{urlsplit(page).netloc}"
        return [
            raw(origin, f"/{p}")[0]
            for p in ["README.md", "tokenizer.json", "onnx/model_quantized.onnx", "file/README.md"]
        ]

    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, ask
    )
    assert code == 0
    assert all(400 <= c < 500 for c in visitor.result), visitor.result


def test_without_a_model_the_model_address_serves_nothing_and_the_page_names_none(
    dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def ask(page: str) -> list[int]:
        origin = f"{urlsplit(page).scheme}://{urlsplit(page).netloc}"
        return [raw(origin, f"/model/{p}")[0] for p in FILES]

    code, visitor = view_with([str(READING / "mosaic.mosaic")], monkeypatch, ask)
    assert code == 0
    assert all(c == 404 for c in visitor.result), visitor.result
    (url,) = visitor.urls
    assert "model" not in parse_qs(urlsplit(url).query)


def test_the_page_address_with_a_model_names_both_the_mosaic_and_the_model(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, lambda _: 0
    )
    assert code == 0
    (url,) = visitor.urls
    assert set(parse_qs(urlsplit(url).query)) >= {"mosaic", "model"}


def test_the_server_with_a_model_listens_on_the_loopback_address_only(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, lambda _: 0
    )
    assert code == 0
    (url,) = visitor.urls
    assert urlsplit(url).hostname == "127.0.0.1"
    assert urlsplit(model_base(url)).hostname == "127.0.0.1"


def test_the_model_stops_being_served_when_the_command_returns(
    model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, visitor = view_with(
        [str(READING / "mosaic.mosaic"), "--model", str(model)], monkeypatch, lambda _: 0
    )
    assert code == 0
    (url,) = visitor.urls
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
        urllib.request.urlopen(urljoin(model_base(url), "tokenizer.json"), timeout=3)


# --- help and the build --------------------------------------------------------------------


def test_view_help_says_the_model_is_given_at_run_time_and_is_optional() -> None:
    run = subprocess.run(
        [str(entry_point()), "view", "--help"], capture_output=True, text=True, check=False
    )
    text = " ".join(run.stdout.split())
    assert run.returncode == 0
    assert "[--model DIR]" in text, "the model is optional (answer A on #117)"
    assert "bun run build" in text, "the viewer is built first, with no model"


PINNED = {
    "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1",  # section 6, model file
    "91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854",  # section 6, tokenizer
}


def test_no_file_of_the_repository_or_the_built_viewer_is_the_model() -> None:
    """Answer A: the model is never bundled into the viewer build, nor committed (CLAUDE.md)."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout.split(b"\0")
    files = [REPO / os.fsdecode(p) for p in listed if p]
    dist = REPO / "viewer" / "dist"
    if dist.is_dir():
        files += list(dist.rglob("*"))
    found = [
        p for p in files if p.is_file() and (p.suffix == ".onnx" or sha(p.read_bytes()) in PINNED)
    ]
    assert found == []
