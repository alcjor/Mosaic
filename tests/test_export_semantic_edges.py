"""Edge cases of ``mosaic export`` with ``search: semantic`` (plan M3.9), from the spec's words.

docs/design.md, View file: ``search: semantic`` is "embedding model inside, about 25 MB". Section 6
pins the model file and the tokenizer by SHA-256. Plan M3.9: the export carries the pinned model
and tokenizer, "checked by hash as ``mosaic view --model`` checks them; a wrong or missing model
file exits 1 naming the file". Section 3.8: a file the reading rules refuse is never exported.
Principle 8: nothing the command is given is written. Principle 5: same inputs, same bytes. The
maintainer's answers: the view file is ``--view FILE`` (#130); ``-o FILE`` is optional with a
default and an existing output is kept (#131). Help: "with search: text it carries no model, and
--model is an error".
"""

import base64
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from mosaic_build import export, view
from mosaic_build.cli import main
from mosaic_build.mosaic import vectors

from tests.conftest import REPO

READING = REPO / "conformance" / "reading"
CASES = json.loads((READING / "cases.json").read_text(encoding="utf-8"))
OPENS = sorted(name for name, case in CASES.items() if case["opens"])
REFUSED = sorted(name for name, case in CASES.items() if not case["opens"])
SEMANTIC = "search: semantic\n"
TEXT = "search: text\n"
# Section 6, written out here from the specification, not read from the code.
SPEC_MODEL_HASH = "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
SPEC_TOKENIZER_HASH = "91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854"
# Every byte value, twice: NUL, newlines, bytes that are no UTF-8 text.
MODEL_BYTES = bytes(range(256)) * 2 + b"\0\0"
TOKENIZER_BYTES = b'{"tokenizer": true}\r\n\xff\xfe\0'
ORT_JS = "const ort = 'ONNX Runtime';\n"
ORT_WASM = b"\0asm-onnx-runtime"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stand_in_dist(directory: Path) -> None:
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
        'const page = "the page"; import("./ort.wasm.bundle.min-C3.js");\n', encoding="utf-8"
    )
    (assets / "index-B2.css").write_text("body { margin: 0; }\n", encoding="utf-8")
    (assets / "sqlite3-D4.wasm").write_bytes(b"\0asm-sqlite-engine")
    (assets / "ort.wasm.bundle.min-C3.js").write_text(ORT_JS, encoding="utf-8")
    (assets / "ort-wasm-simd-threaded-E5.wasm").write_bytes(ORT_WASM)


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the built viewer, laid out as ``bun run build`` lays it out."""
    directory = tmp_path / "dist"
    stand_in_dist(directory)
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def pinned_stand_in() -> vectors.Model:
    return vectors.Model(
        name=vectors.MODEL.name,
        repository=vectors.MODEL.repository,
        revision=vectors.MODEL.revision,
        licence=vectors.MODEL.licence,
        files=(
            vectors.PinnedFile("onnx/model_quantized.onnx", sha(MODEL_BYTES)),
            vectors.PinnedFile("tokenizer.json", sha(TOKENIZER_BYTES)),
        ),
    )


@pytest.fixture
def model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in model pinned by its own hashes (the real one is 23 MB)."""
    directory = tmp_path / "model"
    (directory / "onnx").mkdir(parents=True)
    (directory / "onnx" / "model_quantized.onnx").write_bytes(MODEL_BYTES)
    (directory / "tokenizer.json").write_bytes(TOKENIZER_BYTES)
    (directory / "README.md").write_bytes(b"not a pinned file, never carried")
    pinned = pinned_stand_in()
    monkeypatch.setattr(view, "MODEL", pinned)
    monkeypatch.setattr(export, "MODEL", pinned)
    return directory


def listing(directory: Path) -> list[tuple[str, int, int]]:
    return sorted(
        (str(p.relative_to(directory)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in directory.rglob("*")
    )


def copied(tmp_path: Path, source: str, name: str | None = None) -> Path:
    path = tmp_path / "in" / (name or source)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(READING / source, path)
    return path


def settings(tmp_path: Path, text: str = SEMANTIC) -> Path:
    path = tmp_path / "views" / "view.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def data_of(page: str) -> dict[str, object]:
    found = re.search(r'<script type="application/json" id="mosaic-export">(.*?)</script>', page)
    assert found, "the export holds no data element"
    return json.loads(found.group(1))


def carried_model(page: str) -> dict[str, object]:
    files = data_of(page)["model"]
    assert isinstance(files, dict)
    return files


def unpacked(text: object) -> bytes:
    return gzip.decompress(base64.b64decode(str(text)))


def run_export(
    tmp_path: Path, model_dir: Path | str | None, *, text: str | None = SEMANTIC, out: str = "o"
) -> tuple[int, Path]:
    target = tmp_path / "out" / f"{out}.html"
    target.parent.mkdir(exist_ok=True)
    args = ["export", str(copied(tmp_path, "mosaic.mosaic")), "-o", str(target)]
    if text is not None:
        args += ["--view", str(settings(tmp_path, text))]
    if model_dir is not None:
        args += ["--model", str(model_dir)]
    return main(args), target


# --- what the export carries (design, View file; section 6) ----------------------------------


def test_the_model_and_tokenizer_are_carried_byte_for_byte_whatever_their_bytes(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    # Section 6: the exact pinned files; binary content with NUL and non-UTF-8 bytes survives.
    code, out = run_export(tmp_path, model)
    assert code == 0
    page = out.read_text(encoding="utf-8")
    files = data_of(page)["model"]
    assert isinstance(files, dict)
    assert unpacked(files["model"]) == MODEL_BYTES
    assert unpacked(files["tokenizer"]) == TOKENIZER_BYTES


def test_only_the_two_pinned_files_are_carried_not_the_rest_of_the_model_directory(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    # Section 6 pins two files; a README or any other file beside them is not part of the model.
    (model / "onnx" / "model.onnx").write_bytes(b"UNPINNED-FULL-PRECISION-MODEL")
    code, out = run_export(tmp_path, model)
    assert code == 0
    page = out.read_bytes()
    carried_files = carried_model(page.decode("utf-8"))
    carried = b"".join(unpacked(v) for v in carried_files.values())
    assert b"UNPINNED" not in carried and b"never carried" not in carried
    assert b"UNPINNED" not in page and b"never carried" not in page
    assert sorted(carried_files) == ["model", "tokenizer"]


def test_the_model_is_never_in_the_page_as_raw_bytes_or_as_a_second_file(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    # "One HTML file": the export is a single new file; no model or runtime file beside it.
    code, out = run_export(tmp_path, model)
    assert code == 0
    assert sorted(p.name for p in out.parent.iterdir()) == [out.name]
    page = out.read_bytes()
    assert MODEL_BYTES not in page and TOKENIZER_BYTES not in page
    assert b"\0asm" not in page  # WebAssembly travels inside the data, packed
    text = page.decode("utf-8")
    assert re.search(r"<(script|link|img|iframe|source)\b[^>]*\b(src|href)=", text) is None


def test_the_runtime_travels_with_the_model_unchanged(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    # Plan M3.9: "the pinned model and tokenizer" and (commit title) ONNX Runtime; unchanged bytes.
    code, out = run_export(tmp_path, model)
    assert code == 0
    ort = data_of(out.read_text(encoding="utf-8"))["ort"]
    assert isinstance(ort, dict)
    assert unpacked(ort["module"]) == ORT_JS.encode()
    assert unpacked(ort["wasm"]) == ORT_WASM


def test_a_semantic_export_keeps_everything_a_text_export_holds(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    # The same page, mosaic, view and SQLite engine; the model only adds.
    _, semantic = run_export(tmp_path, model, out="semantic")
    _, text = run_export(tmp_path, None, text=TEXT, out="text")
    one = data_of(semantic.read_text(encoding="utf-8"))
    two = data_of(text.read_text(encoding="utf-8"))
    assert one["mosaic"] == two["mosaic"] and one["sqlite"] == two["sqlite"]
    assert one["name"] == two["name"]
    assert semantic.stat().st_size > text.stat().st_size
    assert "model" in one and "model" not in two and "ort" not in two


def test_without_view_the_default_search_is_semantic_and_carries_the_model(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    # #120: every key is optional and search defaults to semantic; a missing --view is the same.
    code, out = run_export(tmp_path, model, text=None)
    assert code == 0
    assert "model" in data_of(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("text", ["", "# nothing\n", "{}\n", "theme: dark\n", SEMANTIC])
def test_a_view_file_that_leaves_search_to_its_default_gets_the_model(
    text: str, tmp_path: Path, dist: Path, model: Path
) -> None:
    code, out = run_export(tmp_path, model, text=text)
    assert code == 0
    assert "model" in data_of(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", OPENS)
def test_every_file_the_reading_rules_open_is_exported_with_the_model(
    name: str, tmp_path: Path, dist: Path, model: Path
) -> None:
    # Section 3.8 / 6: a tessera, a mosaic of another vector model or none, WAL: all open; the
    # mosaic's own vectors do not decide whether the page can carry the model.
    path = copied(tmp_path, name)
    before = path.read_bytes()
    out = tmp_path / "out.html"
    args = ["export", str(path), "--view", str(settings(tmp_path)), "-o", str(out)]
    assert main([*args, "--model", str(model)]) == 0
    page = out.read_text(encoding="utf-8")
    assert unpacked(data_of(page)["mosaic"]) == before
    assert unpacked(carried_model(page)["model"]) == MODEL_BYTES


def test_the_same_inputs_give_the_same_bytes_with_the_model(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    # Principle 5 / design: same inputs, same export, wherever and whenever.
    mosaic, view_path = copied(tmp_path, "mosaic.mosaic"), settings(tmp_path)
    one, two = tmp_path / "one.html", tmp_path / "two.html"
    base = ["export", str(mosaic), "--view", str(view_path), "--model", str(model)]
    assert main([*base, "-o", str(one)]) == 0
    os.utime(model / "tokenizer.json", (1, 1))  # a changed time is not a changed model
    assert main([*base, "-o", str(two)]) == 0
    assert one.read_bytes() == two.read_bytes()


def test_a_relative_model_path_and_one_with_a_trailing_slash_give_the_same_export(
    tmp_path: Path, dist: Path, model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mosaic, view_path = copied(tmp_path, "mosaic.mosaic"), settings(tmp_path)
    absolute, relative, slash = tmp_path / "a.html", tmp_path / "r.html", tmp_path / "s.html"
    first = ["export", str(mosaic), "--view", str(view_path), "--model", str(model)]
    assert main([*first, "-o", str(absolute)]) == 0
    monkeypatch.chdir(tmp_path)
    args = ["export", str(mosaic), "--view", str(view_path)]
    assert main([*args, "-o", str(relative), "--model", "model"]) == 0
    assert main([*args, "-o", str(slash), "--model", f"{model}/"]) == 0
    assert absolute.read_bytes() == relative.read_bytes() == slash.read_bytes()


def test_a_symlinked_model_directory_and_symlinked_files_are_carried(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    real = tmp_path / "real-model"
    model.rename(real)
    model.symlink_to(real, target_is_directory=True)
    code, out = run_export(tmp_path, model)
    assert code == 0
    assert unpacked(carried_model(out.read_text(encoding="utf-8"))["model"]) == MODEL_BYTES


# --- a wrong or missing model file exits 1 naming it (plan M3.9) -----------------------------


@pytest.mark.parametrize("path", ["onnx/model_quantized.onnx", "tokenizer.json"])
def test_each_missing_pinned_file_exits_1_naming_it_and_writes_nothing(
    path: str, tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (model / path).unlink()
    code, out = run_export(tmp_path, model)
    err = capsys.readouterr().err
    assert code == 1
    assert Path(path).name in err and "Traceback" not in err
    assert not out.exists()


@pytest.mark.parametrize("path", ["onnx/model_quantized.onnx", "tokenizer.json"])
@pytest.mark.parametrize("kind", ["empty", "appended", "truncated", "flipped"])
def test_each_pinned_file_with_other_bytes_exits_1_naming_it_and_both_hashes(
    path: str,
    kind: str,
    tmp_path: Path,
    dist: Path,
    model: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    good = (model / path).read_bytes()
    bad = {
        "empty": b"",
        "appended": good + b"\0",
        "truncated": good[:-1],
        "flipped": bytes([good[0] ^ 1]) + good[1:],
    }[kind]
    (model / path).write_bytes(bad)
    code, out = run_export(tmp_path, model)
    err = capsys.readouterr().err
    assert code == 1
    assert Path(path).name in err
    assert sha(bad) in err and sha(good) in err
    assert "Traceback" not in err
    assert not out.exists()


@pytest.mark.parametrize("path", ["onnx/model_quantized.onnx", "tokenizer.json"])
def test_a_pinned_file_that_is_a_directory_exits_1_naming_it(
    path: str, tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (model / path).unlink()
    (model / path).mkdir()
    code, out = run_export(tmp_path, model)
    err = capsys.readouterr().err
    assert code == 1 and Path(path).name in err and "Traceback" not in err
    assert not out.exists()


def test_a_model_directory_that_is_empty_exits_1_naming_a_pinned_file(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty-model"
    empty.mkdir()
    code, out = run_export(tmp_path, empty)
    err = capsys.readouterr().err
    assert code == 1 and ("model_quantized.onnx" in err or "tokenizer.json" in err)
    assert not out.exists()


def test_a_model_that_is_a_file_not_a_directory_exits_1_naming_it(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "model-is-a-file"
    file.write_bytes(b"x")
    code, out = run_export(tmp_path, file)
    err = capsys.readouterr().err
    assert code == 1 and str(file) in err and "Traceback" not in err
    assert not out.exists()


@pytest.mark.parametrize("given", ["", "\0"])
def test_an_empty_or_nul_model_argument_exits_1_and_writes_nothing(
    given: str, tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run_export(tmp_path, given)
    err = capsys.readouterr().err
    assert code == 1 and "Traceback" not in err
    assert not out.exists()


def test_both_pinned_files_wrong_still_exits_1_naming_at_least_one_and_writes_nothing(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (model / "tokenizer.json").write_bytes(b"x")
    (model / "onnx" / "model_quantized.onnx").write_bytes(b"y")
    code, out = run_export(tmp_path, model)
    err = capsys.readouterr().err
    assert code == 1
    assert "tokenizer.json" in err or "model_quantized.onnx" in err
    assert not out.exists()


def test_the_pinned_hashes_are_those_of_section_6(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No stand-in pins here: a directory of invented files is refused with the hashes the
    # specification gives, so the command is checking the real model.
    fake = tmp_path / "fake"
    (fake / "onnx").mkdir(parents=True)
    (fake / "onnx" / "model_quantized.onnx").write_bytes(b"not the model")
    (fake / "tokenizer.json").write_bytes(b"not the tokenizer")
    code, out = run_export(tmp_path, fake)
    err = capsys.readouterr().err
    assert code == 1
    assert SPEC_MODEL_HASH in err or SPEC_TOKENIZER_HASH in err
    assert not out.exists()


def test_a_wrong_tokenizer_beside_a_right_model_names_the_tokenizer_only(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (model / "tokenizer.json").write_bytes(MODEL_BYTES)  # swapped contents of the other file
    code, _ = run_export(tmp_path, model)
    err = capsys.readouterr().err
    assert code == 1 and "tokenizer.json" in err
    assert "model_quantized.onnx" not in err.replace(str(model), "")


@pytest.mark.parametrize("breakage", ["missing", "changed", "empty"])
def test_the_error_of_export_names_what_the_error_of_view_names(
    breakage: str,
    tmp_path: Path,
    dist: Path,
    model: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Plan M3.9: checked "as `mosaic view --model` checks them": the same file, the same hashes.
    tokenizer = model / "tokenizer.json"
    if breakage == "missing":
        tokenizer.unlink()
    else:
        tokenizer.write_bytes(b"" if breakage == "empty" else b"another")
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a page was opened"))
    mosaic = copied(tmp_path, "mosaic.mosaic")
    assert main(["view", str(mosaic), "--model", str(model)]) == 1
    seen = capsys.readouterr().err
    code, _ = run_export(tmp_path, model)
    got = capsys.readouterr().err
    assert code == 1
    for hash_ in re.findall(r"\b[0-9a-f]{64}\b", seen):
        assert hash_ in got
    assert "tokenizer.json" in got


# --- failures write nothing and leave every input as it was ----------------------------------


def test_a_model_error_leaves_every_directory_as_it_was_and_prints_nothing_on_stdout(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (model / "tokenizer.json").write_bytes(b"changed")
    mosaic = copied(tmp_path, "mosaic.mosaic")
    view_path = settings(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    watched = [tmp_path / "in", tmp_path / "views", model, out_dir, dist]
    before = [listing(d) for d in watched]
    blob = mosaic.read_bytes()
    args = ["export", str(mosaic), "--view", str(view_path), "-o", str(out_dir / "x.html")]
    assert main([*args, "--model", str(model)]) == 1
    assert capsys.readouterr().out == ""
    assert [listing(d) for d in watched] == before
    assert mosaic.read_bytes() == blob


def test_a_success_writes_only_the_output_and_leaves_the_model_and_sources_alone(
    tmp_path: Path, dist: Path, model: Path
) -> None:
    mosaic = copied(tmp_path, "mosaic.mosaic")
    view_path = settings(tmp_path)
    watched = [tmp_path / "in", tmp_path / "views", model, dist]
    before = [listing(d) for d in watched]
    out = tmp_path / "elsewhere" / "x.html"
    out.parent.mkdir()
    args = ["export", str(mosaic), "--view", str(view_path), "-o", str(out)]
    assert main([*args, "--model", str(model)]) == 0
    assert [listing(d) for d in watched] == before
    assert sorted(p.name for p in out.parent.iterdir()) == ["x.html"]


@pytest.mark.parametrize("name", REFUSED)
def test_a_refused_mosaic_is_refused_with_a_good_model_and_writes_nothing(
    name: str, tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Section 3.8: the reading rules decide first; a good model does not make a bad file exportable.
    path = copied(tmp_path, name)
    out = tmp_path / "out.html"
    args = ["export", str(path), "--view", str(settings(tmp_path)), "-o", str(out)]
    assert main([*args, "--model", str(model)]) == 1
    assert capsys.readouterr().err.startswith("mosaic export: ")
    assert not out.exists()


def test_a_missing_mosaic_is_an_error_naming_it_even_with_a_good_model(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "in" / "nothing.mosaic"
    out = tmp_path / "out.html"
    args = ["export", str(missing), "--view", str(settings(tmp_path)), "-o", str(out)]
    assert main([*args, "--model", str(model)]) == 1
    assert str(missing) in capsys.readouterr().err
    assert not out.exists()


def test_an_existing_output_is_kept_with_the_model_and_the_model_is_not_the_reason(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # #131: an existing output is kept (exit 1, naming it), even when the model would also be bad.
    out = tmp_path / "out.html"
    out.write_bytes(b"keep me")
    (model / "tokenizer.json").write_bytes(b"changed")
    mosaic = copied(tmp_path, "mosaic.mosaic")
    args = ["export", str(mosaic), "--view", str(settings(tmp_path)), "-o", str(out)]
    assert main([*args, "--model", str(model)]) == 1
    assert capsys.readouterr().err.startswith("mosaic export: ")
    assert out.read_bytes() == b"keep me"


def test_an_existing_output_is_kept_when_the_model_is_good(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.html"
    out.write_bytes(b"keep me")
    code, _ = run_export(tmp_path, model, out="ignored")
    assert code == 0  # a different output works
    mosaic = copied(tmp_path, "mosaic.mosaic")
    args = ["export", str(mosaic), "--view", str(settings(tmp_path)), "-o", str(out)]
    assert main([*args, "--model", str(model)]) == 1
    assert str(out) in capsys.readouterr().err
    assert out.read_bytes() == b"keep me"


def test_the_default_output_name_is_used_with_the_model(
    tmp_path: Path, dist: Path, model: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #131: without -o, the file's name with .html in the current directory.
    mosaic = copied(tmp_path, "mosaic.mosaic", "netflix.mosaic")
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    assert (
        main(["export", str(mosaic), "--view", str(settings(tmp_path)), "--model", str(model)]) == 0
    )
    assert [p.name for p in here.iterdir()] == ["netflix.html"]


def test_a_wrong_view_file_is_refused_before_the_model_matters(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    view_path = settings(tmp_path, "search: fuzzy\n")
    out = tmp_path / "out.html"
    mosaic = copied(tmp_path, "mosaic.mosaic")
    args = ["export", str(mosaic), "--view", str(view_path), "-o", str(out)]
    assert main([*args, "--model", str(model)]) == 1
    assert str(view_path) in capsys.readouterr().err
    assert not out.exists()


# --- search: text and --model ----------------------------------------------------------------


def test_search_text_with_a_good_model_is_an_error_and_writes_nothing(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run_export(tmp_path, model, text=TEXT)
    assert code == 1
    assert "model" in capsys.readouterr().err
    assert not out.exists()


def test_search_text_with_a_missing_model_directory_is_still_an_error_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run_export(tmp_path, tmp_path / "no-model", text=TEXT)
    assert code == 1 and capsys.readouterr().err != ""
    assert not out.exists()


def test_search_semantic_without_a_model_names_the_option_and_writes_nothing(
    tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run_export(tmp_path, None)
    assert code == 1 and "--model" in capsys.readouterr().err
    assert not out.exists()


def test_model_without_a_value_is_a_usage_error(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mosaic = copied(tmp_path, "mosaic.mosaic")
    with pytest.raises(SystemExit) as stop:
        main(["export", str(mosaic), "--view", str(settings(tmp_path)), "--model"])
    assert stop.value.code == 2


# --- the viewer build the export is made from -------------------------------------------------


@pytest.mark.parametrize("missing", ["ort.wasm.bundle.min-C3.js", "ort-wasm-simd-threaded-E5.wasm"])
def test_a_build_without_the_onnx_runtime_exits_1_and_writes_nothing(
    missing: str, tmp_path: Path, dist: Path, model: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A semantic export with no runtime to carry cannot search by vectors offline: it must not
    # silently write a page that lacks it.
    (dist / "assets" / missing).unlink()
    code, out = run_export(tmp_path, model)
    err = capsys.readouterr().err
    assert code == 1 and "Traceback" not in err and err.startswith("mosaic export: ")
    assert not out.exists()


def test_a_text_export_does_not_need_the_onnx_runtime_in_the_build(
    tmp_path: Path, dist: Path
) -> None:
    for path in (dist / "assets").glob("ort*"):
        path.unlink()
    code, out = run_export(tmp_path, None, text=TEXT)
    assert code == 0 and "ort" not in data_of(out.read_text(encoding="utf-8"))


# --- the real built viewer and the real model (slow) -----------------------------------------


@pytest.mark.slow
def test_the_real_semantic_export_is_about_25_megabytes_and_fetches_nothing(tmp_path: Path) -> None:
    # Design, View file: `search: semantic` is "embedding model inside, about 25 MB". The model is
    # 23 MB (section 6) and the ONNX Runtime's WebAssembly 14 MB; both travel gzipped and base64.
    from tests.conftest import MODEL  # the files `scripts/fetch_model.py` puts in .cache

    if not (MODEL / "tokenizer.json").is_file():
        pytest.skip("the model is not fetched: uv run python scripts/fetch_model.py")
    bun = shutil.which("bun")
    assert bun, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    built = subprocess.run(
        [bun, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert built.returncode == 0, built.stdout + built.stderr
    mosaic = copied(tmp_path, "mosaic.mosaic")
    args = ["export", str(mosaic), "--view", str(settings(tmp_path)), "--model", str(MODEL)]
    one, two = tmp_path / "one.html", tmp_path / "two.html"
    assert main([*args, "-o", str(one)]) == 0
    assert main([*args, "-o", str(two)]) == 0
    size = one.stat().st_size
    print(f"\nreal semantic export of a {mosaic.stat().st_size}-byte mosaic: {size:,} bytes")
    print(f"sha256 {sha(one.read_bytes())}")
    assert one.read_bytes() == two.read_bytes()
    assert 20_000_000 < size < 32_000_000  # "about 25 MB", for a mosaic of 135 KB
    page = one.read_text(encoding="utf-8")
    assert re.search(r"<(script|link|img|iframe|source)\b[^>]*\b(src|href)=", page) is None
    data = data_of(page)
    model_files = data["model"]
    assert isinstance(model_files, dict)
    assert sha(unpacked(model_files["model"])) == SPEC_MODEL_HASH
    assert sha(unpacked(model_files["tokenizer"])) == SPEC_TOKENIZER_HASH
