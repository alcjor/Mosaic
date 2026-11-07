"""Edge cases of ``mosaic export`` (plan M3.8), written from the spec and the command's help.

docs/design.md, Implementation plan, Viewer: "``mosaic export`` saves the same page with the
mosaic inside as one HTML file that opens offline with a double-click"; View file: ``search:
text``. Section 3.8 (reading rules) decides which files may be exported. Principle 8: never write
to a source. Principle 5: same inputs, same bytes. The maintainer's answers: the view file is
``--view FILE`` (#130); ``-o FILE`` is optional and defaults to the file's name with ``.html`` in
the current directory; an existing output is kept (#131). Help: "A missing or refused file, a
wrong view file or an existing output file is an error naming it (exit status 1), and nothing is
written."
"""

import base64
import gzip
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from mosaic_build import view
from mosaic_build.cli import main

from tests.conftest import REPO

READING = REPO / "conformance" / "reading"
CASES = json.loads((READING / "cases.json").read_text(encoding="utf-8"))
OPENS = sorted(name for name, case in CASES.items() if case["opens"])
REFUSED = sorted(name for name, case in CASES.items() if not case["opens"])
TEXT = "search: text\n"


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
    (assets / "index-A1.js").write_text('const page = "the page";\n', encoding="utf-8")
    (assets / "index-B2.css").write_text("body { margin: 0; }\n", encoding="utf-8")
    (assets / "sqlite3-D4.wasm").write_bytes(b"\0asm-sqlite-engine")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def listing(directory: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(directory)), p.stat().st_size) for p in directory.rglob("*"))


def copied(tmp_path: Path, source: str, name: str | None = None, where: str = "in") -> Path:
    path = tmp_path / where / (name or source)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(READING / source, path)
    return path


def settings(tmp_path: Path, text: str = TEXT) -> Path:
    path = tmp_path / "views" / "view.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def data_of(page: str) -> dict[str, object]:
    found = re.search(r'<script type="application/json" id="mosaic-export">(.*?)</script>', page)
    assert found, "the export holds no data element"
    return json.loads(found.group(1))


def unpacked(text: object) -> bytes:
    return gzip.decompress(base64.b64decode(str(text)))


# --- every file the reading rules open can be exported (section 3.8) ------------------------


@pytest.mark.parametrize("name", OPENS)
def test_every_file_the_reading_rules_open_is_exported_whole_and_its_source_is_left_alone(
    name: str, tmp_path: Path, dist: Path
) -> None:
    # Section 3.8 / conformance/reading: wal.mosaic is in WAL mode, where opening it could
    # leave -wal and -shm files beside the source; principle 8.
    path = copied(tmp_path, name)
    before_bytes, before_dir = path.read_bytes(), listing(path.parent)
    mtime = path.stat().st_mtime_ns
    out = tmp_path / "out" / "export.html"
    out.parent.mkdir()
    assert main(["export", str(path), "--view", str(settings(tmp_path)), "-o", str(out)]) == 0
    data = data_of(out.read_text(encoding="utf-8"))
    assert unpacked(data["mosaic"]) == before_bytes
    assert data["name"] == name
    assert path.read_bytes() == before_bytes
    assert listing(path.parent) == before_dir
    assert path.stat().st_mtime_ns == mtime


@pytest.mark.parametrize("name", REFUSED)
def test_a_refused_file_leaves_its_directory_and_the_output_directory_as_they_were(
    name: str, tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Help: "a missing or refused file ... is an error naming it (exit status 1), and nothing
    # is written."
    path = copied(tmp_path, name)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    before = listing(path.parent), listing(out_dir)
    code = main(["export", str(path), "--view", str(settings(tmp_path)), "-o", str(out_dir / "e")])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert name in captured.err
    assert (listing(path.parent), listing(out_dir)) == before


def test_a_truncated_mosaic_is_refused_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Section 3.8: an untrusted or corrupt file is refused by the reading rules.
    path = copied(tmp_path, "mosaic.mosaic", "cut.mosaic")
    path.write_bytes(path.read_bytes()[: 4096 * 3])
    out = tmp_path / "out.html"
    assert main(["export", str(path), "--view", str(settings(tmp_path)), "-o", str(out)]) == 1
    assert "cut.mosaic" in capsys.readouterr().err
    assert not out.exists()


def test_a_file_of_nul_bytes_is_refused_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nul.mosaic"
    path.write_bytes(b"\0" * 8192)
    out = tmp_path / "out.html"
    assert main(["export", str(path), "--view", str(settings(tmp_path)), "-o", str(out)]) == 1
    assert "nul.mosaic" in capsys.readouterr().err
    assert not out.exists()


def test_a_directory_given_as_the_file_is_refused_naming_it(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "folder.mosaic"
    folder.mkdir()
    out = tmp_path / "out.html"
    assert main(["export", str(folder), "--view", str(settings(tmp_path)), "-o", str(out)]) == 1
    assert "folder.mosaic" in capsys.readouterr().err
    assert not out.exists()


# --- the output file ------------------------------------------------------------------------


def test_an_output_in_a_directory_that_does_not_exist_exits_1_naming_it_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = copied(tmp_path, "mosaic.mosaic")
    out = tmp_path / "nowhere" / "export.html"
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("mosaic export: ") and "nowhere" in err
    assert not (tmp_path / "nowhere").exists()


def test_an_output_that_is_a_directory_exits_1_and_leaves_it_alone(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = copied(tmp_path, "mosaic.mosaic")
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("keep", encoding="utf-8")
    before = listing(out)
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(out)]) == 1
    assert str(out) in capsys.readouterr().err
    assert listing(out) == before


def test_an_output_that_is_the_source_itself_is_kept_and_exits_1(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Principle 8: never write to a source; the output "is never overwritten".
    source = copied(tmp_path, "mosaic.mosaic")
    before = source.read_bytes()
    code = main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(source)])
    assert code == 1
    assert str(source) in capsys.readouterr().err
    assert source.read_bytes() == before


def test_an_empty_existing_output_is_still_kept(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = copied(tmp_path, "mosaic.mosaic")
    out = tmp_path / "empty.html"
    out.write_bytes(b"")
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(out)]) == 1
    assert "exists" in capsys.readouterr().err
    assert out.read_bytes() == b""


def test_a_symlink_as_output_is_never_written_through(tmp_path: Path, dist: Path) -> None:
    # "The output is never overwritten": an existing name, even a link to nothing, is kept.
    source = copied(tmp_path, "mosaic.mosaic")
    target = tmp_path / "elsewhere.html"
    link = tmp_path / "link.html"
    link.symlink_to(target)
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(link)]) == 1
    assert not target.exists()
    assert link.is_symlink()
    target.write_text("keep", encoding="utf-8")
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(link)]) == 1
    assert target.read_text(encoding="utf-8") == "keep"


def test_every_failure_leaves_the_output_directory_exactly_as_it_was(
    tmp_path: Path, dist: Path
) -> None:
    # "Nothing is written": no half-written or temporary file is left beside the output.
    source = copied(tmp_path, "mosaic.mosaic")
    refused = copied(tmp_path, "node-changed.mosaic")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "earlier.html").write_text("earlier", encoding="utf-8")
    before = listing(out_dir)
    out = str(out_dir / "new.html")
    good = str(settings(tmp_path))
    bad = str(settings(tmp_path, "search: text\ntheme: sepia\n"))
    semantic = str(settings(tmp_path, "search: semantic\n"))
    for args in (
        [str(refused), "--view", good, "-o", out],
        [str(source), "--view", bad, "-o", out],
        [str(source), "--view", semantic, "-o", out],
        [str(source), "--view", str(tmp_path / "absent.yaml"), "-o", out],
        [str(tmp_path / "absent.mosaic"), "--view", good, "-o", out],
        [str(source), "--view", good, "-o", str(out_dir / "earlier.html")],
    ):
        assert main(["export", *args]) == 1, args
        assert listing(out_dir) == before, args


# --- the view file ---------------------------------------------------------------------------


def test_a_missing_view_file_exits_1_naming_it_and_writes_nothing(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.html"
    missing = tmp_path / "absent.yaml"
    source = copied(tmp_path, "mosaic.mosaic")
    assert main(["export", str(source), "--view", str(missing), "-o", str(out)]) == 1
    assert str(missing) in capsys.readouterr().err
    assert not out.exists()


def test_a_view_file_that_is_a_directory_exits_1_naming_it(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.html"
    folder = tmp_path / "view.yaml"
    folder.mkdir()
    source = copied(tmp_path, "mosaic.mosaic")
    assert main(["export", str(source), "--view", str(folder), "-o", str(out)]) == 1
    assert str(folder) in capsys.readouterr().err
    assert not out.exists()


def test_a_view_file_that_is_not_utf8_exits_1_naming_it(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "view.yaml"
    bad.write_bytes(b"search: text\n# \xff\xfe\n")
    out = tmp_path / "out.html"
    source = copied(tmp_path, "mosaic.mosaic")
    assert main(["export", str(source), "--view", str(bad), "-o", str(out)]) == 1
    assert str(bad) in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize(
    "text",
    [
        "search: text\nbogus: 1\n",
        "search: text\ntypes: [Item]\n",
        "- search: text\n",
        "search: [text]\n",
    ],
    ids=["unknown-key", "types-as-list", "top-level-list", "search-as-list"],
)
def test_a_wrong_view_file_is_refused_even_when_search_is_text(
    text: str, tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # View file keys, values and defaults as answered on #120; a wrong file is an error naming it.
    bad = settings(tmp_path, text)
    out = tmp_path / "out.html"
    source = copied(tmp_path, "mosaic.mosaic")
    assert main(["export", str(source), "--view", str(bad), "-o", str(out)]) == 1
    assert str(bad) in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("text", ["", "# nothing here\n", "{}\n", "types: {}\n"])
def test_a_view_file_that_leaves_search_to_its_default_is_semantic_and_refused_until_m3_9(
    text: str, tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every key is optional and `search` defaults to `semantic` (#120, Question 1); the help:
    # "its search setting must be text (search: semantic ... comes later)".
    out = tmp_path / "out.html"
    source = copied(tmp_path, "mosaic.mosaic")
    assert (
        main(["export", str(source), "--view", str(settings(tmp_path, text)), "-o", str(out)]) == 1
    )
    assert capsys.readouterr().err.startswith("mosaic export: ")
    assert not out.exists()


def test_view_file_labels_with_markup_stay_inside_the_data_element_and_round_trip(
    tmp_path: Path, dist: Path
) -> None:
    label = 'Café 日本語 </script><script>alert(1)</script> <!-- &amp; "q"'
    text = f"search: text\ntypes:\n  Item:\n    label: {json.dumps(label)}\n"
    out = tmp_path / "out.html"
    source = copied(tmp_path, "mosaic.mosaic")
    assert (
        main(["export", str(source), "--view", str(settings(tmp_path, text)), "-o", str(out)]) == 0
    )
    page = out.read_text(encoding="utf-8")
    assert page.count("<script") == 2 and page.count("</script") == 2
    assert "<!--" not in page
    view_data: dict[str, list[dict[str, object]]] = json.loads(json.dumps(data_of(page)["view"]))
    types = view_data["types"]
    assert [t["label"] for t in types] == [label]


def test_a_non_ascii_file_name_is_kept_in_the_export(tmp_path: Path, dist: Path) -> None:
    source = copied(tmp_path, "mosaic.mosaic", "café-日本-\U0001f600.mosaic")
    out = tmp_path / "out.html"
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(out)]) == 0
    assert data_of(out.read_text(encoding="utf-8"))["name"] == source.name


# --- default output name ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "default"),
    [("Netflix.MOSAIC", "Netflix.html"), ("café.mosaic", "café.html")],
)
def test_without_o_the_default_keeps_the_stem_as_written(
    name: str,
    default: str,
    tmp_path: Path,
    dist: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Help: "the output is FILE's name with .html for its suffix, in the current directory."
    source = copied(tmp_path, "mosaic.mosaic", name)
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    assert main(["export", str(source), "--view", str(settings(tmp_path))]) == 0
    assert [p.name for p in here.iterdir()] == [default]
    assert default in capsys.readouterr().out
    assert not source.with_suffix(".html").exists()


def test_without_o_a_relative_source_in_the_current_directory_writes_beside_it(
    tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = tmp_path / "here"
    here.mkdir()
    shutil.copyfile(READING / "tessera.tessera", here / "rows.tessera")
    view_path = settings(tmp_path)
    monkeypatch.chdir(here)
    assert main(["export", "rows.tessera", "--view", str(view_path)]) == 0
    assert sorted(p.name for p in here.iterdir()) == ["rows.html", "rows.tessera"]


# --- command line ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--view"],
        ["x.mosaic", "-o"],
        ["x.mosaic", "--view"],
        ["x.mosaic", "y.mosaic"],
        ["--view", "v.yaml"],
        ["x.mosaic", "--no-such-option"],
    ],
    ids=[
        "no-file",
        "o-without-value",
        "view-without-value",
        "two-files",
        "no-file-with-view",
        "unknown-option",
    ],
)
def test_a_command_line_not_understood_exits_2(
    args: list[str], tmp_path: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as stop:
        main(["export", *args])
    assert stop.value.code == 2
    assert list(tmp_path.glob("*.html")) == []


def test_the_help_names_the_view_file_and_output_options_and_the_default_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["export", "--help"])
    assert stop.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "--view FILE" in text and "-o FILE" in text and ".html" in text


# --- determinism (principle 5) ---------------------------------------------------------------


def test_the_same_inputs_give_the_same_bytes_wherever_and_whenever_they_are_exported(
    tmp_path: Path, dist: Path
) -> None:
    one = copied(tmp_path, "mosaic.mosaic", "same.mosaic", where="a")
    two = copied(tmp_path, "mosaic.mosaic", "same.mosaic", where="b/deeper")
    os.utime(two, (1_000_000_000, 1_000_000_000))
    v1 = settings(tmp_path, "search: text\ntheme: dark\n")
    v2 = tmp_path / "views" / "other.yaml"
    v2.write_text("# a comment\ntheme:   dark   # same\n\nsearch: text\n", encoding="utf-8")
    out1, out2 = tmp_path / "1.html", tmp_path / "2.html"
    assert main(["export", str(one), "--view", str(v1), "-o", str(out1)]) == 0
    time.sleep(1.1)  # a clock in the gzip header would show now
    assert main(["export", str(two), "--view", str(v2), "-o", str(out2)]) == 0
    assert out1.read_bytes() == out2.read_bytes()


def test_a_different_view_file_gives_a_different_page_and_the_same_mosaic_bytes(
    tmp_path: Path, dist: Path
) -> None:
    source = copied(tmp_path, "mosaic.mosaic")
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    assert (
        main(
            [
                "export",
                str(source),
                "--view",
                str(settings(tmp_path, "search: text\ntheme: dark\n")),
                "-o",
                str(a),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "export",
                str(source),
                "--view",
                str(settings(tmp_path, "search: text\ntheme: light\n")),
                "-o",
                str(b),
            ]
        )
        == 0
    )
    da, db = data_of(a.read_text(encoding="utf-8")), data_of(b.read_text(encoding="utf-8"))
    assert da["view"] != db["view"]
    assert da["mosaic"] == db["mosaic"]


# --- the real built viewer (slow) ------------------------------------------------------------


def built() -> str:
    bun = shutil.which("bun")
    assert bun, "bun is needed to build the viewer (CLAUDE.md, Commands)"
    run = subprocess.run(
        [bun, "run", "build"], cwd=REPO / "viewer", capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
    return bun


@pytest.mark.slow
def test_the_real_export_fetches_nothing_and_stays_a_few_megabytes(tmp_path: Path) -> None:
    # Design, View file: `search: text` is "a few MB"; plan M3.8: no embedding model and no ONNX
    # Runtime. A page that fetches nothing has no external script, style, image or frame.
    built()
    out = tmp_path / "real.html"
    source = copied(tmp_path, "mosaic.mosaic")
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(out)]) == 0
    size = out.stat().st_size
    print(f"\nreal export of a {source.stat().st_size}-byte mosaic: {size:,} bytes")
    page = out.read_text(encoding="utf-8")
    assert size < 5_000_000
    assert (
        re.search(r"<(script|link|img|iframe|source|video|audio)\b[^>]*\b(src|href)=", page) is None
    )
    assert 'rel="stylesheet"' not in page
    assert b"\0asm" not in out.read_bytes()  # no raw WebAssembly: it travels inside the data
    # The ONNX Runtime's WebAssembly is 14 MB; SQLite's is 0.9 MB.
    assert size < 14_000_000


@pytest.mark.slow
@pytest.mark.parametrize(
    ("name", "query", "node", "kind"),
    [
        ("tessera.tessera", "Row two", "Row:2", "Row"),
        ("non-ascii.mosaic", "Item B", "Item:b", "Item"),
        ("wal.mosaic", "Item B", "Item:b", "Item"),
        ("stat4.mosaic", "Item B", "Item:b", "Item"),
    ],
)
def test_every_file_the_reading_rules_open_exports_to_a_page_that_opens_offline(
    name: str, query: str, node: str, kind: str, tmp_path: Path
) -> None:
    bun = built()
    source = copied(tmp_path, name)
    page = tmp_path / "page.html"
    assert main(["export", str(source), "--view", str(settings(tmp_path)), "-o", str(page)]) == 0
    run = subprocess.run(
        [bun, "viewer/scripts/open-export.ts", str(page), query, node, kind],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    seen = json.loads(run.stdout.strip().splitlines()[-1])
    assert seen["blocked"] == [] and seen["errors"] == [] and seen["alerts"] == [], seen
    assert any(r["id"] == node for r in seen["results"])
    assert node in seen["rows"]
    assert seen["header"][0] == name
