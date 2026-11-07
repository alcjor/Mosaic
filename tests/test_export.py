"""``mosaic export FILE [--view VIEW] -o OUT.html``: one HTML file that opens offline (plan M3.8).

docs/design.md, Implementation plan, Viewer: "``mosaic export`` saves the same page with the
mosaic inside as one HTML file that opens offline with a double-click"; View file: ``search:
text``, "a few MB". The export holds the page, the kit and the mosaic, shaped by a view file; a
file the reading rules refuse exits 1 and writes nothing; the source is never written
(principle 8); the export carries no embedding model and no ONNX Runtime. These tests use a
stand-in for the built viewer; ``tests/viewer/test_export_page.py`` opens a real export in a
browser.
"""

import base64
import gzip
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest
from mosaic_build import export, view, view_file
from mosaic_build.cli import main

from tests.conftest import REPO

READING = REPO / "conformance" / "reading"
CASES = json.loads((READING / "cases.json").read_text(encoding="utf-8"))
REFUSED = sorted(name for name, case in CASES.items() if not case["opens"])
TEXT = "search: text\ntypes:\n  Item:\n    label: Thing\n"
ONNX = b"onnx-runtime-would-be-here"
SQLITE = b"\0asm-sqlite-engine"


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the built viewer, laid out as ``bun run build`` lays it out."""
    directory = tmp_path / "dist"
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text(
        "<!doctype html>\n<html><head>\n"
        '<script type="module" crossorigin src="./assets/index-A1.js"></script>\n'
        '<link rel="stylesheet" crossorigin href="./assets/index-B2.css">\n'
        '</head><body><div id="app"></div></body></html>\n',
        encoding="utf-8",
    )
    (assets / "index-A1.js").write_text(
        'const page = "the page and the kit"; import("./ort.wasm.bundle.min-C3.js");\n',
        encoding="utf-8",
    )
    (assets / "index-B2.css").write_text("body { margin: 0; }\n", encoding="utf-8")
    (assets / "sqlite3-D4.wasm").write_bytes(SQLITE)
    (assets / "ort.wasm.bundle.min-C3.js").write_text("const ort = 'ONNX Runtime';\n", "utf-8")
    (assets / "ort-wasm-simd-threaded-E5.wasm").write_bytes(ONNX)
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def files_in(directory: Path) -> list[str]:
    return sorted(str(p.relative_to(directory)) for p in directory.rglob("*"))


def source(tmp_path: Path, name: str = "mosaic.mosaic") -> Path:
    path = tmp_path / "in" / name
    path.parent.mkdir(exist_ok=True)
    shutil.copyfile(READING / "mosaic.mosaic", path)
    return path


def view_yaml(tmp_path: Path, text: str = TEXT) -> Path:
    path = tmp_path / "in" / "view.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def unpacked(text: object) -> bytes:
    """The bytes the page unpacks: base64, then gzip."""
    return gzip.decompress(base64.b64decode(str(text)))


def data_of(page: str) -> dict[str, object]:
    found = re.search(r'<script type="application/json" id="mosaic-export">(.*?)</script>', page)
    assert found, "the export holds no data element"
    return json.loads(found.group(1))


def test_one_html_file_holds_the_page_the_kit_and_the_mosaic_shaped_by_the_view_file(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mosaic, settings = source(tmp_path), view_yaml(tmp_path)
    out = tmp_path / "out" / "export.html"
    out.parent.mkdir()
    before = files_in(tmp_path / "in"), mosaic.read_bytes(), settings.read_bytes()
    assert main(["export", str(mosaic), "--view", str(settings), "-o", str(out)]) == 0
    assert str(out) in capsys.readouterr().out
    assert files_in(tmp_path / "out") == ["export.html"]
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert 'const page = "the page and the kit"' in page  # the script, inlined
    assert "body { margin: 0; }" in page  # the stylesheet, inlined
    assert 'src="./assets' not in page and 'href="./assets' not in page  # nothing to fetch
    data = data_of(page)
    assert data["name"] == "mosaic.mosaic"
    assert unpacked(data["mosaic"]) == mosaic.read_bytes()
    assert unpacked(data["sqlite"]) == SQLITE
    assert data["view"] == view_file.read(settings).as_json()
    assert (files_in(tmp_path / "in"), mosaic.read_bytes(), settings.read_bytes()) == before


def test_the_export_carries_no_embedding_model_and_no_onnx_runtime(
    tmp_path: Path, dist: Path
) -> None:
    out = tmp_path / "export.html"
    assert (
        main(["export", str(source(tmp_path)), "--view", str(view_yaml(tmp_path)), "-o", str(out)])
        == 0
    )
    page = out.read_bytes()
    assert b"ONNX Runtime" not in page
    data = data_of(page.decode("utf-8"))
    assert sorted(data) == ["mosaic", "name", "sqlite", "view"]
    assert ONNX not in page and ONNX not in unpacked(data["mosaic"]) + unpacked(data["sqlite"])


@pytest.mark.parametrize("name", REFUSED)
def test_a_file_the_reading_rules_refuse_exits_1_and_writes_nothing(
    name: str, tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "in" / name
    path.parent.mkdir()
    shutil.copyfile(READING / name, path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    out = tmp_path / "export.html"
    assert main(["export", str(path), "--view", str(view_yaml(tmp_path)), "-o", str(out)]) == 1
    assert capsys.readouterr().err.startswith(f"mosaic export: {path}")
    assert not out.exists()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_a_missing_file_exits_1_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "export.html"
    missing = tmp_path / "absent.mosaic"
    assert main(["export", str(missing), "--view", str(view_yaml(tmp_path)), "-o", str(out)]) == 1
    assert str(missing) in capsys.readouterr().err
    assert not out.exists()


def test_a_wrong_view_file_exits_1_with_its_error_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "export.html"
    bad = view_yaml(tmp_path, "search: text\ntheme: sepia\n")
    assert main(["export", str(source(tmp_path)), "--view", str(bad), "-o", str(out)]) == 1
    assert capsys.readouterr().err.startswith(f"mosaic export: {bad}:2: view file: theme")
    assert not out.exists()


@pytest.mark.parametrize("text", [None, "search: semantic\n", "theme: dark\n"])
def test_search_semantic_is_not_built_yet_and_writes_nothing(
    text: str | None, tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "export.html"
    args = ["export", str(source(tmp_path)), "-o", str(out)]
    if text is not None:
        args += ["--view", str(view_yaml(tmp_path, text))]
    assert main(args) == 1
    err = capsys.readouterr().err
    assert "search is semantic" in err and "M3.9" in err
    assert not out.exists()


def test_an_existing_output_is_never_overwritten(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "export.html"
    out.write_text("keep me", encoding="utf-8")
    assert (
        main(["export", str(source(tmp_path)), "--view", str(view_yaml(tmp_path)), "-o", str(out)])
        == 1
    )
    assert (
        capsys.readouterr().err == f"mosaic export: {out}: exists; an export is never overwritten\n"
    )
    assert out.read_text(encoding="utf-8") == "keep me"


def test_without_o_the_export_is_the_file_name_with_html_in_the_current_directory(
    tmp_path: Path,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Answer on #131: (a) Reading B, an optional -o FILE with a default; (b) Reading A, kept.
    mosaic, settings = source(tmp_path, "netflix.mosaic"), view_yaml(tmp_path)
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    assert main(["export", str(mosaic), "--view", str(settings)]) == 0
    assert files_in(here) == ["netflix.html"]
    assert "netflix.html" in capsys.readouterr().out
    first = (here / "netflix.html").read_bytes()
    assert unpacked(data_of(first.decode("utf-8"))["mosaic"]) == mosaic.read_bytes()
    # Run twice: the second keeps the first export and exits 1.
    assert main(["export", str(mosaic), "--view", str(settings)]) == 1
    err = capsys.readouterr().err
    assert err == "mosaic export: netflix.html: exists; an export is never overwritten\n"
    assert (here / "netflix.html").read_bytes() == first


@pytest.mark.parametrize(
    ("name", "default"),
    [
        ("netflix.mosaic", "netflix.html"),
        ("rows.tessera", "rows.html"),
        ("archive.v2.mosaic", "archive.v2.html"),
        ("plain", "plain.html"),
    ],
)
def test_the_default_output_name(name: str, default: str) -> None:
    assert export.default_output(Path("/elsewhere") / name) == Path(default)


def test_a_refused_file_without_o_writes_nothing_and_keeps_an_earlier_export(
    tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    refused = tmp_path / "in" / "mosaic.mosaic"
    refused.parent.mkdir()
    shutil.copyfile(READING / REFUSED[0], refused)
    assert main(["export", str(refused), "--view", str(view_yaml(tmp_path))]) == 1
    assert files_in(here) == []
    (here / "mosaic.html").write_text("earlier export", encoding="utf-8")
    assert main(["export", str(refused), "--view", str(view_yaml(tmp_path))]) == 1
    assert (here / "mosaic.html").read_text(encoding="utf-8") == "earlier export"


def test_an_unbuilt_viewer_exits_1_saying_how_to_build_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(view, "VIEWER_DIST", tmp_path / "nowhere")
    out = tmp_path / "export.html"
    assert (
        main(["export", str(source(tmp_path)), "--view", str(view_yaml(tmp_path)), "-o", str(out)])
        == 1
    )
    assert "bun run build" in capsys.readouterr().err
    assert not out.exists()


def test_text_from_the_file_name_cannot_break_out_of_the_page(tmp_path: Path, dist: Path) -> None:
    mosaic = source(tmp_path, "a<!--<script>&b.mosaic")
    out = tmp_path / "export.html"
    assert main(["export", str(mosaic), "--view", str(view_yaml(tmp_path)), "-o", str(out)]) == 0
    page = out.read_text(encoding="utf-8")
    assert page.count("<script") == 2  # the data element and the page's script, nothing more
    assert "<!--" not in page
    assert "<title>a&lt;!--&lt;script&gt;&amp;b.mosaic · Mosaic</title>" in page
    assert data_of(page)["name"] == "a<!--<script>&b.mosaic"


def test_a_build_whose_script_would_end_its_element_is_refused(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (dist / "assets" / "index-A1.js").write_text('const s = "</script>";\n', encoding="utf-8")
    out = tmp_path / "export.html"
    assert (
        main(["export", str(source(tmp_path)), "--view", str(view_yaml(tmp_path)), "-o", str(out)])
        == 1
    )
    assert "cannot be inlined" in capsys.readouterr().err
    assert not out.exists()


def test_the_same_inputs_give_the_same_export(tmp_path: Path, dist: Path) -> None:
    mosaic, settings = source(tmp_path), view_yaml(tmp_path)
    one, two = tmp_path / "one.html", tmp_path / "two.html"
    export.export(mosaic, one, settings)
    export.export(mosaic, two, settings)
    assert one.read_bytes() == two.read_bytes()


@pytest.mark.parametrize("given", [".", "/"])
def test_a_path_with_no_file_name_exits_1_naming_it(
    given: str,
    tmp_path: Path,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["export", given, "--view", str(view_yaml(tmp_path))]) == 1
    assert capsys.readouterr().err == f"mosaic export: {given}: no such file\n"
    assert not [p for p in files_in(tmp_path) if p.endswith(".html") and not p.startswith("dist")]


def test_a_file_name_that_is_not_utf8_exits_1_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "in"
    directory.mkdir()
    raw = os.fsencode(directory) + b"/bad\xff.mosaic"
    shutil.copyfile(READING / "mosaic.mosaic", raw)
    path = Path(os.fsdecode(raw))
    out = tmp_path / "out.html"
    assert main(["export", str(path), "--view", str(view_yaml(tmp_path)), "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert "bad\\xff.mosaic: its file name is not UTF-8 text" in err
    assert not out.exists()
