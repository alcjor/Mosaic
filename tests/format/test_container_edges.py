"""Edge cases of the container rules for M2.1, after the maintainer's answers on #104.

* B: a tessera or mosaic stores its text as UTF-8 (Spec 0.1 section 3.1); every reader refuses
  a UTF-16 file and ``mosaic check`` fails it under ``container``.
* C: ``sqlite_stat4`` may be present, as ``sqlite_stat1`` may (section 3.1).
* The ``search`` table has format.sql's definition (section 3.1: "with the same definitions").

The TypeScript kit has the same cases in ``kit/test/container.edges.test.ts``.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest
from mosaic_build.cli import main
from mosaic_format import seal
from mosaic_format.check import check_file
from mosaic_format.reader import FileRefusedError
from mosaic_format.reader import open as open_sealed

from tests.conftest import REPO
from tests.format.test_check import mif
from tests.format.test_reader import tamper

READING = REPO / "conformance" / "reading"
FORMAT_SQL = (REPO / "spec" / "format.sql").read_text("utf-8")
STAT4 = "CREATE TABLE sqlite_stat4(tbl,idx,neq,nlt,ndlt,sample)"


def utf16_file(path: Path, encoding: str, producer: str = "tool/1") -> Path:
    """A file made from format.sql whose text is stored as ``encoding`` (UTF-16le or be)."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute(f"PRAGMA encoding = '{encoding}'")
        con.executescript(FORMAT_SQL)
        con.execute(
            "INSERT INTO header (one, format_version, kind, producer, knowledge_hash) "
            "VALUES (1, '0.1', 'tessera', ?, ?)",
            (producer, "0" * 64),
        )
        assert con.execute("PRAGMA encoding").fetchone() == (encoding,)
    finally:
        con.close()
    return path


def with_stat4(path: Path, *rows: str) -> None:
    """Declare ``sqlite_stat4`` as SQLite does (``sqlite_`` is reserved), then add ``rows``."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute(STAT4.replace("sqlite_stat4", "stat4_placeholder"))
        con.execute("PRAGMA writable_schema = ON")
        con.execute(
            "UPDATE sqlite_schema SET name = 'sqlite_stat4', tbl_name = 'sqlite_stat4', sql = ? "
            "WHERE name = 'stat4_placeholder'",
            (STAT4,),
        )
        con.execute("PRAGMA writable_schema = OFF")
    finally:
        con.close()
    con = sqlite3.connect(path, isolation_level=None)
    try:
        for row in rows:
            con.execute(row)
    finally:
        con.close()


@pytest.fixture
def tessera(tmp_path: Path) -> Path:
    path = tmp_path / "t.tessera"
    seal(path, mif.tessera())
    return path


def container_violations(path: Path) -> list[str]:
    report = check_file(path, pieces=[])
    assert report.rules == {"container"}, [str(v) for v in report.violations]
    return [str(v) for v in report.violations]


# --- B: text is UTF-8 ---------------------------------------------------------------------


@pytest.mark.parametrize("encoding", ["UTF-16le", "UTF-16be"])
def test_a_file_stored_as_utf_16_is_refused_for_its_encoding(tmp_path: Path, encoding: str) -> None:
    path = utf16_file(tmp_path / "u16.tessera", encoding)
    with pytest.raises(FileRefusedError) as refused:
        open_sealed(path)
    assert str(refused.value).startswith(f"{path}: ")
    assert "UTF-16" in str(refused.value)


@pytest.mark.parametrize("encoding", ["UTF-16le", "UTF-16be"])
def test_mosaic_check_fails_a_utf_16_file_under_container(tmp_path: Path, encoding: str) -> None:
    path = utf16_file(tmp_path / "u16.tessera", encoding)
    (message,) = container_violations(path)
    assert "UTF-16" in message
    assert message.endswith("[container, section 3.1]")


def test_a_utf_16_file_with_non_ascii_header_text_is_still_refused_for_its_encoding(
    tmp_path: Path,
) -> None:
    path = utf16_file(tmp_path / "wide.tessera", "UTF-16le", producer="ツール🧩/1")
    (message,) = container_violations(path)
    assert "UTF-16" in message


def test_mosaic_check_exits_non_zero_for_the_utf_16_file_and_zero_for_stat4(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["check", str(READING / "utf-16.mosaic")]) != 0
    out = capsys.readouterr()
    assert "container" in out.out + out.err
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    shutil.copy(READING / "tessera.tessera", pieces)
    assert main(["check", str(READING / "stat4.mosaic"), "--pieces", str(pieces)]) == 0


def test_a_file_whose_encoding_flag_says_utf_16_is_refused(tessera: Path) -> None:
    data = bytearray(tessera.read_bytes())
    data[59] = 2  # text encoding field of the SQLite header: UTF-16le
    tessera.write_bytes(bytes(data))
    with pytest.raises(FileRefusedError) as refused:
        open_sealed(tessera)
    assert str(refused.value).startswith(f"{tessera}: ")


# --- C: sqlite_stat4 may be present --------------------------------------------------------


def test_a_tessera_holding_sqlite_stat4_opens_and_passes_the_check(tessera: Path) -> None:
    with open_sealed(tessera) as before:
        header = dict(before.header)
    with_stat4(tessera)
    with open_sealed(tessera) as sealed:
        assert dict(sealed.header) == header
    report = check_file(tessera, pieces=[])
    assert report.ok, [str(v) for v in report.violations]


def test_a_file_holding_stat1_and_stat4_with_rows_that_no_statistics_give_still_opens(
    tessera: Path,
) -> None:
    with_stat4(
        tessera,
        "INSERT INTO sqlite_stat4 VALUES ('node', 'nothing', 'x y z', '1', '2', x'00ff')",
        "INSERT INTO sqlite_stat4 VALUES (NULL, NULL, NULL, NULL, NULL, NULL)",
        "INSERT INTO sqlite_stat1 VALUES ('ghost', NULL, '-5 -5')",
    )
    with open_sealed(tessera) as sealed:
        assert sealed.header["kind"] == "tessera"
    assert check_file(tessera, pieces=[]).ok


def test_sqlite_stat4_does_not_excuse_an_extra_table(tessera: Path) -> None:
    with_stat4(tessera)
    tamper(tessera, "CREATE TABLE extra (x)")
    with pytest.raises(FileRefusedError):
        open_sealed(tessera)
    (message,) = container_violations(tessera)
    assert "extra" in message


def test_a_table_that_only_looks_like_a_statistics_table_is_an_extra_table(tessera: Path) -> None:
    tamper(tessera, STAT4.replace("sqlite_stat4", "stat4_placeholder"))
    with pytest.raises(FileRefusedError):
        open_sealed(tessera)
    container_violations(tessera)


# --- the search table has format.sql's definition ----------------------------------------


@pytest.mark.parametrize(
    "definition",
    [
        "label, aliases, summary, snippets, content = '', tokenize = 'unicode61'",
        "label, aliases, summary, snippets, content = '', tokenize = \"unicode61 tokenchars '-_'\"",
        "label, aliases, summary, snippets, tokenize = \"unicode61 tokenchars '-_.'\"",
        "aliases, label, summary, snippets, content = '', "
        "tokenize = \"unicode61 tokenchars '-_.'\"",
        "label, aliases, summary, snippets, content = '', prefix = '2', "
        "tokenize = \"unicode61 tokenchars '-_.'\"",
    ],
)
def test_a_search_table_with_another_definition_is_refused(tessera: Path, definition: str) -> None:
    tamper(
        tessera,
        "DROP TABLE search",
        f"CREATE VIRTUAL TABLE search USING fts5 ({definition})",
    )
    with pytest.raises(FileRefusedError) as refused:
        open_sealed(tessera)
    assert "schema" in str(refused.value)
    container_violations(tessera)


def test_a_table_named_like_a_shadow_table_of_search_is_an_extra_table(tessera: Path) -> None:
    tamper(tessera, "CREATE TABLE search_extra (x)")
    with pytest.raises(FileRefusedError):
        open_sealed(tessera)
    container_violations(tessera)
