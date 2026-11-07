"""Which types an export carries (plan M3.10; docs/design.md, View file).

The view file's ``export.types`` (M3.5, answer on #120) names the node types an export carries;
what it means beyond that is asked on this slice's PR. This file starts with what is settled:
with ``export.types`` absent, the export carries the mosaic as it is, byte for byte, so the page
shows the mosaic's own knowledge hash.
"""

import base64
import gzip
import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from mosaic_build import cut, view
from mosaic_build.cli import main
from mosaic_format.check import check_file
from mosaic_format.reader import open as open_sealed

from tests.conftest import REPO

MOSAIC = REPO / "conformance" / "reading" / "mosaic.mosaic"


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text(
        '<script type="module" crossorigin src="./assets/index-A.js"></script>\n'
        '<link rel="stylesheet" crossorigin href="./assets/index-B.css">\n',
        encoding="utf-8",
    )
    (directory / "assets" / "index-A.js").write_text("const page = 1;\n", encoding="utf-8")
    (directory / "assets" / "index-B.css").write_text("body {}\n", encoding="utf-8")
    (directory / "assets" / "sqlite3-C.wasm").write_bytes(b"\0asm")
    monkeypatch.setattr(view, "VIEWER_DIST", directory)
    return directory


def carried(page: Path) -> bytes:
    found = re.search(r'id="mosaic-export">(.*?)</script>', page.read_text(encoding="utf-8"))
    assert found
    return gzip.decompress(base64.b64decode(json.loads(found.group(1))["mosaic"]))


def test_without_export_types_the_export_carries_the_mosaic_as_it_is(
    tmp_path: Path, dist: Path
) -> None:
    source = tmp_path / "mosaic.mosaic"
    shutil.copyfile(MOSAIC, source)
    settings = tmp_path / "view.yaml"
    settings.write_text("search: text\ntypes:\n  Item: {}\n", encoding="utf-8")
    page = tmp_path / "out.html"
    assert main(["export", str(source), "--view", str(settings), "-o", str(page)]) == 0
    assert carried(page) == MOSAIC.read_bytes()


# The answers on #140. Q1, Reading B: the cut is a build with the source mosaic as its one piece,
# pinned by its knowledge hash. Q2, Reading A: a type the mosaic lacks, or none, is an error.


def export(tmp_path: Path, text: str, out: str = "out.html") -> tuple[int, Path, Path]:
    source = tmp_path / "mosaic.mosaic"
    if not source.exists():
        shutil.copyfile(MOSAIC, source)
    settings = tmp_path / "view.yaml"
    settings.write_text(text, encoding="utf-8")
    page = tmp_path / out
    return main(["export", str(source), "--view", str(settings), "-o", str(page)]), page, settings


def opened(tmp_path: Path, data: bytes) -> sqlite3.Connection:
    path = tmp_path / "carried.mosaic"
    path.write_bytes(data)
    return sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)


ITEM_ONLY = "search: text\nexport:\n  types: [Item]\n"
BOTH = "search: text\nexport:\n  types: [Item, Group]\n"


def test_an_export_of_some_types_carries_those_types_and_no_other(
    tmp_path: Path, dist: Path
) -> None:
    code, page, _ = export(tmp_path, ITEM_ONLY)
    assert code == 0
    con = opened(tmp_path, carried(page))
    assert con.execute("SELECT name, kind FROM type ORDER BY name").fetchall() == [("Item", "node")]
    assert con.execute("SELECT id FROM node ORDER BY id").fetchall() == [("Item:a",), ("Item:b",)]
    assert con.execute("SELECT count(*) FROM edge").fetchone() == (0,)


def test_edges_are_carried_when_both_ends_are(tmp_path: Path, dist: Path) -> None:
    code, page, _ = export(tmp_path, BOTH)
    assert code == 0
    con = opened(tmp_path, carried(page))
    assert [r[0] for r in con.execute("SELECT name FROM type ORDER BY name")] == [
        "Group",
        "Item",
        "in_group",
    ]
    assert con.execute("SELECT count(*) FROM edge").fetchone() == (2,)


def test_the_carried_mosaic_opens_by_the_reading_rules_and_passes_the_checker(
    tmp_path: Path, dist: Path
) -> None:
    code, page, _ = export(tmp_path, BOTH)
    assert code == 0
    path = tmp_path / "carried.mosaic"
    path.write_bytes(carried(page))
    with open_sealed(path) as sealed:  # section 3.8: both hashes checked
        assert sealed.kind == "mosaic"
    assert list(check_file(path).violations) == []


def test_the_cut_is_a_build_with_the_source_mosaic_as_its_one_piece(
    tmp_path: Path, dist: Path
) -> None:
    code, page, _ = export(tmp_path, ITEM_ONLY)
    assert code == 0
    source_hash = open_sealed(MOSAIC).knowledge_hash
    con = opened(tmp_path, carried(page))
    pieces = con.execute("SELECT id, kind, hash FROM source WHERE kind IN ('tessera', 'mosaic')")
    assert pieces.fetchall() == [("mosaic", "mosaic", source_hash)]
    for sid, via in con.execute("SELECT sid, via FROM evidence"):
        assert json.loads(via)[-1] == source_hash  # section 3.5
        (copied,) = con.execute("SELECT id FROM source WHERE sid = ?", (sid,)).fetchone()
        assert copied.startswith("mosaic/")  # section 3.2: the piece's rows, prefixed
    pattern_hash, target = con.execute("SELECT pattern_hash, target FROM header").fetchone()
    assert target == "export" and len(pattern_hash) == 64
    assert con.execute("SELECT knowledge_hash FROM header").fetchone()[0] != source_hash


def test_the_same_mosaic_and_types_give_the_same_export(tmp_path: Path, dist: Path) -> None:
    assert export(tmp_path, ITEM_ONLY, "one.html")[0] == 0
    assert export(tmp_path, ITEM_ONLY, "two.html")[0] == 0
    assert (tmp_path / "one.html").read_bytes() == (tmp_path / "two.html").read_bytes()


def test_the_source_is_never_written(tmp_path: Path, dist: Path) -> None:
    source = tmp_path / "mosaic.mosaic"
    shutil.copyfile(MOSAIC, source)
    before = source.read_bytes(), source.stat().st_mtime_ns
    assert export(tmp_path, BOTH)[0] == 0
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "dist",
        "mosaic.mosaic",
        "out.html",
        "view.yaml",
    ]


def test_the_page_keeps_the_source_s_file_name(tmp_path: Path, dist: Path) -> None:
    code, page, _ = export(tmp_path, ITEM_ONLY)
    assert code == 0
    found = re.search(r'id="mosaic-export">(.*?)</script>', page.read_text(encoding="utf-8"))
    assert found and json.loads(found.group(1))["name"] == "mosaic.mosaic"


@pytest.mark.parametrize(
    ("types", "line", "message"),
    [
        ("[Item, Nope]", 3, "export.types: the mosaic has no node type Nope"),
        ("[in_group]", 3, "export.types: the mosaic has no node type in_group"),
        ("[item]", 3, "export.types: the mosaic has no node type item"),
        ("[]", 3, "export.types is empty; name the types to carry"),
    ],
)
def test_a_type_the_mosaic_lacks_or_none_is_an_error_naming_the_file_line_and_setting(
    tmp_path: Path,
    dist: Path,
    capsys: pytest.CaptureFixture[str],
    types: str,
    line: int,
    message: str,
) -> None:
    code, page, settings = export(tmp_path, f"search: text\nexport:\n  types: {types}\n")
    assert code == 1
    assert capsys.readouterr().err == f"mosaic export: {settings}:{line}: view file: {message}\n"
    assert not page.exists()


def test_the_unknown_type_named_is_on_its_own_line(
    tmp_path: Path, dist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "search: text\nexport:\n  types:\n    - Item\n    - Nope\n"
    code, _, settings = export(tmp_path, text)
    assert code == 1
    assert capsys.readouterr().err.startswith(f"mosaic export: {settings}:5: view file:")


def test_piece_names_come_from_the_source_file_name() -> None:
    assert cut.piece_name(Path("netflix.mosaic")) == "netflix"
    assert cut.piece_name(Path("/x/default.mosaic")) == "default"
    assert cut.piece_name(Path("a b.c.mosaic")) == "a-b-c"
    assert cut.piece_name(Path("---.mosaic")) == "source"
