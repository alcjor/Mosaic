"""``mosaic import sqlite``: one SQLite database to one tessera (plan M3.2).

The settings come from a file, as ``mosaic import csv --settings`` reads its own (issue #18):
the file has the shape of the tessera's ``header.settings`` (Specification 0.1 sections 3.3 and
4.3). A wrong setting, also one the database does not match (an unknown table or column, a
foreign key it does not have), is an error naming the settings file, the line and the setting,
exit status 1, and no tessera is written. A file that is not a SQLite database is an error
naming the file. The source is only read (principle 8).
"""

import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest
from mosaic_build.cli import main
from mosaic_format.reader import open as open_sealed

from tests.test_cli import entry_point

SCHEMA = """
CREATE TABLE Writer (WriterId INTEGER PRIMARY KEY, Name TEXT NOT NULL, Born TEXT);
CREATE TABLE Volume (
    VolumeId INTEGER PRIMARY KEY,
    Title    TEXT NOT NULL,
    Pages    INTEGER,
    WriterId INTEGER REFERENCES Writer (WriterId),
    Shelf    TEXT
);
INSERT INTO Writer VALUES (1, 'Ada Quill', '3 March 1901'), (2, 'Bo Lark', 'spring');
INSERT INTO Volume VALUES (10, 'Salt Roads', 312, 1, 'A1'), (11, 'Quiet Hours', NULL, 2, NULL);
"""
"""An invented library: two tables and one foreign key."""

SETTINGS = """\
tables:
  Writer:
    label: Name
    props: [Name, Born]
    convert:
      Born: {kind: date, formats: ["%d %B %Y"]}
  Volume:
    label: Title
    props: [Title, Pages]
    foreign_keys:
      WriterId: written_by
"""

HASH = re.compile(r"\b[0-9a-f]{64}\b")


def _library(directory: Path) -> tuple[Path, Path]:
    """The invented database and its settings file in ``directory``."""
    db = directory / "library.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    settings = directory / "settings.yaml"
    settings.write_text(SETTINGS, encoding="utf-8")
    return db, settings


def _import(db: Path, settings: Path, out: Path) -> int:
    return main(["import", "sqlite", str(db), "--settings", str(settings), "-o", str(out)])


# --- importing ----------------------------------------------------------------------------


def test_import_sqlite_then_check_on_the_installed_entry_point(tmp_path: Path) -> None:
    db, settings = _library(tmp_path)
    out = tmp_path / "pieces" / "library.tessera"
    done = subprocess.run(
        [str(entry_point()), "import", "sqlite", str(db), "--settings", str(settings), "-o",
         str(out)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    with open_sealed(out) as sealed:
        assert f"knowledge_hash {sealed.knowledge_hash}" in done.stdout
        assert sealed.query("SELECT id FROM node ORDER BY id") == [
            ("Volume:10",),
            ("Volume:11",),
            ("Writer:1",),
            ("Writer:2",),
        ]
        assert sealed.query("SELECT type, src, dst FROM v_edge ORDER BY src") == [
            ("written_by", "Volume:10", "Writer:1"),
            ("written_by", "Volume:11", "Writer:2"),
        ]
    assert f"tessera {out}" in done.stdout
    assert main(["check", str(out)]) == 0


def test_import_records_the_settings_file_as_header_settings(tmp_path: Path) -> None:
    db, settings = _library(tmp_path)
    out = tmp_path / "library.tessera"
    assert _import(db, settings, out) == 0
    with open_sealed(out) as sealed:
        ((recorded,),) = sealed.query("SELECT settings FROM header")
    assert json.loads(str(recorded)) == {
        "tables": {
            "Writer": {
                "type": "Writer",
                "label": "Name",
                "summary": None,
                "props": ["Name", "Born"],
                "convert": {"Born": {"kind": "date", "formats": ["%d %B %Y"]}},
            },
            "Volume": {
                "type": "Volume",
                "label": "Title",
                "summary": None,
                "props": ["Title", "Pages"],
                "foreign_keys": {"WriterId": "written_by"},
            },
        }
    }


def test_header_settings_as_a_settings_file_gives_the_same_tessera(tmp_path: Path) -> None:
    """A tessera's own ``header.settings`` (JSON is YAML) rebuilds it: same knowledge hash."""
    db, settings = _library(tmp_path)
    first = tmp_path / "first.tessera"
    assert _import(db, settings, first) == 0
    with open_sealed(first) as sealed:
        ((recorded,),) = sealed.query("SELECT settings FROM header")
        knowledge_hash = sealed.knowledge_hash
    again = tmp_path / "settings.json"
    again.write_text(str(recorded), encoding="utf-8")
    second = tmp_path / "second.tessera"
    assert _import(db, again, second) == 0
    with open_sealed(second) as sealed:
        assert sealed.knowledge_hash == knowledge_hash


def test_import_prints_the_full_knowledge_hash_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, settings = _library(tmp_path)
    out = tmp_path / "library.tessera"
    assert _import(db, settings, out) == 0
    with open_sealed(out) as sealed:
        assert HASH.findall(capsys.readouterr().out) == [sealed.knowledge_hash]


def test_values_a_conversion_cannot_read_are_listed_on_standard_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, settings = _library(tmp_path)
    assert _import(db, settings, tmp_path / "library.tessera") == 0
    err = capsys.readouterr().err
    assert "Writer.Born" in err and "1 value kept as text" in err and "row 2" in err


def test_the_database_is_byte_identical_after_import(tmp_path: Path) -> None:
    db, settings = _library(tmp_path)
    before = db.read_bytes()
    listing = sorted(p.name for p in tmp_path.iterdir())
    assert _import(db, settings, tmp_path / "out" / "library.tessera") == 0
    assert db.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*listing, "out"])


def test_import_refuses_an_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, settings = _library(tmp_path)
    out = tmp_path / "library.tessera"
    assert _import(db, settings, out) == 0
    before = out.read_bytes()
    capsys.readouterr()
    assert _import(db, settings, out) == 1
    assert str(out) in capsys.readouterr().err
    assert out.read_bytes() == before


# --- wrong settings: the file, the line and the setting ------------------------------------


@pytest.mark.parametrize(
    ("settings", "line", "named"),
    [
        # A table the database does not have.
        ("tables:\n  Writer: {}\n  Reader: {}\n", 3, "tables.Reader"),
        # A column it does not have, as label, summary, a prop or a foreign key.
        ("tables:\n  Writer:\n    label: Title\n", 3, "tables.Writer.label"),
        ("tables:\n  Writer:\n    summary: Note\n", 3, "tables.Writer.summary"),
        ("tables:\n  Writer:\n    props:\n      - Name\n      - Died\n", 5, "tables.Writer.props"),
        (
            "tables:\n  Writer: {}\n  Volume:\n    foreign_keys:\n      Author: written_by\n",
            5,
            "tables.Volume.foreign_keys.Author",
        ),
        # A foreign key the database does not have.
        (
            "tables:\n  Writer: {}\n  Volume:\n    foreign_keys:\n      Shelf: kept_on\n",
            5,
            "tables.Volume.foreign_keys.Shelf",
        ),
        # A foreign key to a table the settings do not name.
        ("tables:\n  Volume:\n    foreign_keys:\n      WriterId: by\n", 4, "foreign_keys.WriterId"),
        # Settings the builder refuses whatever the database.
        ("tables:\n  Writer:\n    colour: red\n", 3, "tables.Writer.colour"),
        ("tables:\n  Writer:\n    type: writer\n", 3, "tables.Writer.type"),
    ],
)
def test_a_wrong_setting_names_the_file_the_line_and_the_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], settings: str, line: int, named: str
) -> None:
    db, path = _library(tmp_path)
    path.write_text(settings, encoding="utf-8")
    out = tmp_path / "library.tessera"
    assert _import(db, path, out) == 1
    err = capsys.readouterr().err
    assert f"{path}:{line}:" in err, err
    assert named in err, err
    assert not out.exists()


def test_a_wrong_setting_names_the_column_or_table_it_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, path = _library(tmp_path)
    path.write_text("tables:\n  Writer:\n    props: [Name, Died]\n", encoding="utf-8")
    assert _import(db, path, tmp_path / "library.tessera") == 1
    err = capsys.readouterr().err
    assert "'Died'" in err and "library.db" in err, err


def test_a_missing_settings_file_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, _ = _library(tmp_path)
    missing = tmp_path / "nothing.yaml"
    out = tmp_path / "library.tessera"
    assert _import(db, missing, out) == 1
    assert "nothing.yaml" in capsys.readouterr().err
    assert not out.exists()


# --- a file that is not a SQLite database ---------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [b"WriterId,Name\n1,Ada Quill\n", b"", b"SQLite format 3\x00" + b"\x00" * 84],
    ids=["csv", "empty", "damaged"],
)
def test_a_file_that_is_not_a_sqlite_database_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    _, settings = _library(tmp_path)
    source = tmp_path / "writers.csv"
    source.write_bytes(content)
    out = tmp_path / "writers.tessera"
    assert _import(source, settings, out) == 1
    err = capsys.readouterr().err
    assert "writers.csv" in err and "not a SQLite database" in err, err
    assert not out.exists()
    assert source.read_bytes() == content


def test_a_missing_database_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, settings = _library(tmp_path)
    out = tmp_path / "library.tessera"
    assert _import(tmp_path / "gone.db", settings, out) == 1
    assert "gone.db" in capsys.readouterr().err
    assert not out.exists()


def test_a_tessera_is_not_a_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db, settings = _library(tmp_path)
    first = tmp_path / "first.tessera"
    assert _import(db, settings, first) == 0
    capsys.readouterr()
    second = tmp_path / "second.tessera"
    assert _import(first, settings, second) == 1
    assert "first.tessera" in capsys.readouterr().err
    assert not second.exists()


# --- help -----------------------------------------------------------------------------------


def test_import_help_lists_the_sqlite_kind(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["import", "--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "sqlite" in out and "csv" in out


def test_import_sqlite_help_documents_the_file_and_its_settings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["import", "sqlite", "--help"])
    assert exit_info.value.code == 0
    out = " ".join(capsys.readouterr().out.split())
    for words in ("SQLite database", "--settings", "header.settings", "-o", "only read"):
        assert words in out, words


def test_import_sqlite_needs_settings_and_output(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["import", "sqlite", "library.db"])
    assert exit_info.value.code == 2
    assert "--settings" in capsys.readouterr().err
