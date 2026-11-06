"""``conformance/reading/``: the Python reader judges each file as ``cases.json`` says (3.8).

The TypeScript kit reads the same files and ``cases.json`` (``kit/test/open.test.ts``), so the
two readers agree on what opens and why the rest is refused.
"""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest
from mosaic_format.check import check_file
from mosaic_format.reader import FileRefusedError
from mosaic_format.reader import open as open_sealed

from tests.conftest import REPO

FILES = REPO / "conformance" / "reading"
CASES: dict[str, dict[str, object]] = json.loads((FILES / "cases.json").read_text("utf-8"))

MESSAGE = {
    "sqlite": "not a readable SQLite 3 database",
    "encoding": "text encoding UTF-16",
    "application_id": "application_id 0x",
    "user_version": "user_version ",
    "format_version": "format version ",
    "schema": "schema does not match format.sql",
    "header": "header ",
    "knowledge_hash": "knowledge hash mismatch",
    "vector_hash": "vector hash mismatch",
}
"""What the Python reader's message says for each rule of ``cases.json``."""


def _load() -> ModuleType:
    path = REPO / "scripts" / "make_reading_files.py"
    spec = importlib.util.spec_from_file_location("make_reading_files", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_reading_files"] = module
    spec.loader.exec_module(module)
    return module


mrf = _load()


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_reader_opens_or_refuses_each_file_as_cases_json_says(name: str) -> None:
    case = CASES[name]
    path = FILES / name
    if case["opens"]:
        with open_sealed(path) as sealed:
            assert dict(sealed.header) == case["header"]
        return
    with pytest.raises(FileRefusedError) as refused:
        open_sealed(path).close()
    message = str(refused.value)
    assert message.startswith(f"{path}: ")
    assert MESSAGE[str(case["rule"])] in message.removeprefix(f"{path}: ")


@pytest.mark.parametrize("name", sorted(CASES))
def test_mosaic_check_passes_the_files_that_open_and_fails_the_others(name: str) -> None:
    pieces = [FILES / mrf.PIECE] if name.endswith(".mosaic") else []
    report = check_file(FILES / name, pieces=pieces)
    assert report.ok is CASES[name]["opens"], [str(v) for v in report.violations]


def test_every_rule_has_a_file_and_both_kinds_open() -> None:
    assert {c["rule"] for c in CASES.values()} == {None, *mrf.RULES}
    opening = sorted(n for n, c in CASES.items() if c["opens"])
    assert opening == [
        "mosaic.mosaic",
        "non-ascii.mosaic",
        "stat4.mosaic",
        "tessera.tessera",
        "wal.mosaic",
    ]
    for name in opening:
        assert CASES[name]["rule"] is None
        header = CASES[name]["header"]
        assert isinstance(header, dict)
        assert header["kind"] == name.rsplit(".", 1)[1]
    assert CASES["wal.mosaic"]["header"] == CASES["mosaic.mosaic"]["header"]
    assert CASES["stat4.mosaic"]["header"] == CASES["mosaic.mosaic"]["header"]


def test_the_utf_16_file_holds_the_conforming_mosaic_stored_as_utf_16() -> None:
    import sqlite3

    def rows(name: str, encoding: str) -> list[tuple[object, ...]]:
        uri = (FILES / name).resolve().as_uri() + "?mode=ro&immutable=1"
        con = sqlite3.connect(uri, uri=True)
        try:
            assert con.execute("PRAGMA encoding").fetchone() == (encoding,)
            return con.execute("SELECT * FROM v_node ORDER BY id").fetchall()
        finally:
            con.close()

    assert rows("utf-16.mosaic", "UTF-16le") == rows("mosaic.mosaic", "UTF-8")


def test_the_files_are_exactly_what_the_script_writes(tmp_path: Path) -> None:
    assert sorted(p.name for p in FILES.iterdir()) == sorted(mrf.outputs())
    mrf.write(tmp_path)
    for name in mrf.outputs():
        assert (tmp_path / name).read_bytes() == (FILES / name).read_bytes(), name


def test_the_readme_lists_every_file_with_its_rule() -> None:
    readme = (FILES / "README.md").read_text("utf-8")
    for name, case in CASES.items():
        row = next(line for line in readme.splitlines() if line.startswith(f"| `{name}` |"))
        assert ("opens" if case["opens"] else f"`{case['rule']}`") in row


@pytest.mark.parametrize(("code", "label"), [(2, "UTF-16le"), (3, "UTF-16be")])
def test_a_file_flagged_utf_16_is_refused_for_its_encoding_as_the_kit_refuses_it(
    tmp_path: Path, code: int, label: str
) -> None:
    data = bytearray((FILES / "mosaic.mosaic").read_bytes())
    data[56:60] = code.to_bytes(4, "big")
    path = tmp_path / "flagged.mosaic"
    path.write_bytes(bytes(data))
    with pytest.raises(FileRefusedError, match=f"text encoding {label}"):
        open_sealed(path).close()


def test_a_header_of_many_rows_is_refused_reading_at_most_two(tmp_path: Path) -> None:
    # CHECK (one = 1) is not enforced on read (section 3.1), so a crafted file can hold any
    # number of header rows; the reader refuses it without reading them all (section 10).
    columns = (
        "format_version, kind, producer, settings, knowledge_hash, vector_hash, embed_model, "
        "pattern_hash, target, ai_model"
    )
    path = tmp_path / "rows.mosaic"
    path.write_bytes((FILES / "mosaic.mosaic").read_bytes())
    mrf.mif.tamper(
        path,
        after=[
            "WITH RECURSIVE n(i) AS (SELECT 2 UNION ALL SELECT i + 1 FROM n WHERE i < 100000) "
            f"INSERT INTO header SELECT n.i, {columns} FROM n, "
            f"(SELECT {columns} FROM header WHERE one = 1)"
        ],
    )
    with pytest.raises(FileRefusedError, match="header has 2 rows or more"):
        open_sealed(path).close()


def test_a_header_with_no_rows_is_said_to_have_0_rows() -> None:
    with pytest.raises(FileRefusedError, match="header has 0 rows"):
        open_sealed(FILES / "no-header.mosaic").close()


HASHES: dict[str, dict[str, object]] = json.loads((FILES / "hashes.json").read_text("utf-8"))

HASH_RULES = {"knowledge_hash": "knowledge_hash", "vector_hash": "vector_hash"}


def test_hashes_json_covers_the_files_that_open_and_those_refused_for_a_hash() -> None:
    reading = {f"reading/{n}" for n, c in CASES.items() if c["opens"] or c["rule"] in HASH_RULES}
    assert reading == {k for k in HASHES if k.startswith("reading/")}
    for name in ("inv-6-hash.tessera", "inv-14-vector-hash.mosaic", "inv-15-piece.tessera"):
        assert f"invalid/files/{name}" in HASHES
    assert HASHES["invalid/files/inv-6-hash.tessera"]["opens"] is False
    assert HASHES["invalid/files/inv-14-vector-hash.mosaic"]["opens"] is False


@pytest.mark.parametrize("key", sorted(HASHES))
def test_each_file_of_hashes_json_opens_with_those_hashes_or_names_the_one_that_differs(
    key: str,
) -> None:
    entry = HASHES[key]
    path = REPO / "conformance" / key
    if entry["opens"]:
        with open_sealed(path) as sealed:
            assert sealed.knowledge_hash == entry["knowledge_hash"]
            assert sealed.vector_hash == entry["vector_hash"]
        return
    with pytest.raises(FileRefusedError) as refused:
        open_sealed(path).close()
    message = str(refused.value)
    if "knowledge hash mismatch" in message:
        assert f"the content gives {entry['knowledge_hash']!r}" in message
    else:
        assert "vector hash mismatch" in message
        assert f"the vectors give {entry['vector_hash']!r}" in message


@pytest.mark.parametrize("name", sorted(n for n, c in CASES.items() if c["rule"] in HASH_RULES))
def test_a_hash_case_differs_from_the_conforming_file_in_one_row_and_the_header_hash(
    name: str,
) -> None:
    base = FILES / ("tessera.tessera" if name.endswith(".tessera") else "mosaic.mosaic")
    header = CASES[base.name]["header"]
    assert isinstance(header, dict)
    with sqlite3.connect(f"{(FILES / name).resolve().as_uri()}?mode=ro&immutable=1", uri=True) as c:
        names = [d[0] for d in c.execute("SELECT * FROM header").description]
        row = dict(zip(names, c.execute("SELECT * FROM header").fetchone(), strict=True))
    assert row == header, "the header is the conforming file's: only the content changed"
    rule = str(CASES[name]["rule"])
    entry = HASHES[f"reading/{name}"]
    assert entry[rule] != header[rule]
    other = "vector_hash" if rule == "knowledge_hash" else "knowledge_hash"
    assert entry[other] == header[other], "the file breaks only its one hash"


def test_the_non_ascii_mosaic_orders_ids_and_aliases_by_utf_8_bytes_not_utf_16() -> None:
    uri = f"{(FILES / 'non-ascii.mosaic').resolve().as_uri()}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as con:
        ids = [i for (i,) in con.execute("SELECT id FROM node ORDER BY nid")]
        aliases = [t for (t,) in con.execute("SELECT text FROM alias ORDER BY text COLLATE NOCASE")]
    keys = [f"Item:{k}" for k in mrf.NON_ASCII]
    by_utf8 = [i for i in ids if i in keys]
    assert by_utf8 == sorted(keys, key=lambda k: k.encode("utf-8"))
    assert by_utf8 != sorted(keys, key=lambda k: k.encode("utf-16-be"))
    assert [a for a in aliases if a in mrf.NON_ASCII] == list(mrf.NON_ASCII)
