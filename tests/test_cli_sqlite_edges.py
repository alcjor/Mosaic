"""Edge cases of ``mosaic import sqlite`` from the command line (plan M3.2).

Written from Specification 0.1 sections 4.1 and 4.3 and the slice's "Done when": a wrong
setting is an error naming the settings file, the line and the setting, exit status 1, and no
tessera is written; a file that is not a SQLite database is an error naming the file; the
same source and settings give the same knowledge hash. Every test runs the command through
``mosaic_build.cli.main`` or the installed entry point, as a user would.
"""

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
    WriterId INTEGER REFERENCES Writer (WriterId)
);
INSERT INTO Writer VALUES (1, 'Ada Quill', '1901'), (2, 'Bo Lark', '1950');
INSERT INTO Volume VALUES (10, 'Salt Roads', 1), (11, 'Quiet Hours', 2);
"""
"""An invented library: two tables and one foreign key."""

GOOD = "tables:\n  Writer:\n    label: Name\n  Volume:\n    label: Title\n"

HASH = re.compile(r"knowledge_hash ([0-9a-f]{64})")


def _db(directory: Path, name: str = "library.db") -> Path:
    path = directory / name
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    return path


def _settings(directory: Path, text: str | bytes, name: str = "settings.yaml") -> Path:
    path = directory / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_bytes(text.encode("utf-8"))  # no newline translation
    return path


def _import(db: Path | str, settings: Path | str, out: Path | str) -> int:
    return main(["import", "sqlite", str(db), "--settings", str(settings), "-o", str(out)])


def _hash(out: str) -> str:
    found = HASH.findall(out)
    assert len(found) == 1, out
    return found[0]


def _refused(
    capsys: pytest.CaptureFixture[str], rc: int, out: Path, db: Path, before: bytes
) -> str:
    """The common promises of a refusal: exit 1, nothing on stdout, no tessera, no traceback."""
    captured = capsys.readouterr()
    assert rc == 1, captured.err
    assert captured.out == "", captured.out
    assert "Traceback" not in captured.err, captured.err
    assert not out.exists()
    assert db.read_bytes() == before
    return captured.err


# --- a wrong setting: the file, the line, the setting, whatever the file looks like ---------


@pytest.mark.parametrize(
    ("text", "line", "named"),
    [
        # Comments and blank lines count as lines.
        ("# header\n\n\ntables:\n  Writer: {}\n  Nope: {}\n", 6, "tables.Nope"),
        # Windows line endings do not shift the line.
        ("tables:\r\n  Writer: {}\r\n  Nope: {}\r\n", 3, "tables.Nope"),
        # Non-ASCII text above the setting does not shift the line.
        ("# écrit par 書き手 — ✓\ntables:\n  Writer: {}\n  Nope: {}\n", 4, "tables.Nope"),
        # A quoted key is the same table.
        ('tables:\n  "Nope": {}\n', 2, "tables.Nope"),
        # The last line has no newline.
        ("tables:\n  Writer: {}\n  Nope: {}", 3, "tables.Nope"),
        # SQLite folds the case of names; the settings name them as the database does.
        ("tables:\n  Writer: {type: Writer}\n  volume: {type: Volume}\n", 3, "tables.volume"),
        ("tables:\n  Writer:\n    props: [name]\n", 3, "tables.Writer.props"),
        ("tables:\n  Writer:\n    label: NAME\n", 3, "tables.Writer.label"),
        # A comment and a blank line inside a list.
        (
            "tables:\n  Writer:\n    props:\n      - Name\n      # next\n\n      - Zip\n",
            7,
            "tables.Writer.props",
        ),
        # Flow style, everything on one line.
        ("tables:\n  Writer: {}\n  Volume: {foreign_keys: {Title: by}}\n", 3, "Title"),
        ("tables: {Writer: {}, Nope: {}}\n", 1, "tables.Nope"),
        # A foreign key on the primary key, on a plain column, or on the parent side.
        (
            "tables:\n  Writer: {}\n  Volume:\n    foreign_keys:\n      VolumeId: by\n",
            5,
            "tables.Volume.foreign_keys.VolumeId",
        ),
        (
            "tables:\n  Writer:\n    foreign_keys:\n      WriterId: by\n",
            4,
            "tables.Writer.foreign_keys.WriterId",
        ),
        # A foreign key column spelled in another case is not the declared column.
        (
            "tables:\n  Writer: {}\n  Volume:\n    foreign_keys:\n      writerid: by\n",
            5,
            "tables.Volume.foreign_keys.writerid",
        ),
        # A name with a control character, a space, or a dot is a name the database lacks.
        ('tables:\n  Writer:\n    label: "Na\\tme"\n', 3, "tables.Writer.label"),
        ("tables:\n  Writer:\n    label: Name Born\n", 3, "tables.Writer.label"),
        ("tables:\n  Writer.Name: {}\n", 2, "Writer.Name"),
        # A table name of the database's own bookkeeping.
        ("tables:\n  sqlite_master: {type: Master}\n", 2, "sqlite_master"),
    ],
    ids=[
        "comments-and-blanks",
        "crlf",
        "non-ascii-above",
        "quoted-key",
        "no-final-newline",
        "table-in-another-case",
        "prop-in-another-case",
        "label-in-another-case",
        "comment-inside-a-list",
        "flow-foreign-key",
        "all-in-one-line",
        "foreign-key-on-the-primary-key",
        "foreign-key-on-the-parent",
        "foreign-key-column-in-another-case",
        "control-character-name",
        "name-with-a-space",
        "name-with-a-dot",
        "internal-table",
    ],
)
def test_a_wrong_setting_names_the_file_the_line_and_the_setting_for_any_layout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, line: int, named: str
) -> None:
    db = _db(tmp_path)
    before = db.read_bytes()
    path = _settings(tmp_path, text)
    out = tmp_path / "deep" / "er" / "library.tessera"
    err = _refused(capsys, _import(db, path, out), out, db, before)
    assert f"{path}:{line}:" in err, err
    assert named in err, err


@pytest.mark.parametrize(
    "case",
    ["unknown-table", "unknown-column", "settings-alone", "not-a-database"],
)
def test_a_refused_import_creates_no_directory_for_the_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Nothing is written: the output's missing folders are not made either."""
    db = _db(tmp_path)
    text = {
        "unknown-table": "tables:\n  Nope: {}\n",
        "unknown-column": "tables:\n  Writer:\n    label: Nope\n",
        "settings-alone": "tables:\n  Writer:\n    colour: red\n",
        "not-a-database": GOOD,
    }[case]
    if case == "not-a-database":
        db = tmp_path / "plain.txt"
        db.write_bytes(b"plain text\n")
    path = _settings(tmp_path, text)
    out = tmp_path / "deep" / "er" / "library.tessera"
    assert _import(db, path, out) == 1
    capsys.readouterr()
    assert not (tmp_path / "deep").exists()


def test_a_setting_the_database_does_not_match_is_found_before_anything_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The good table is valid, the bad one is last: still no tessera, not even a partial one."""
    db = _db(tmp_path)
    before = db.read_bytes()
    path = _settings(tmp_path, GOOD + "  Zzz: {}\n")
    out = tmp_path / "library.tessera"
    err = _refused(capsys, _import(db, path, out), out, db, before)
    assert f"{path}:6:" in err and "Zzz" in err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["library.db", "settings.yaml"]


def test_with_two_wrong_settings_the_line_named_holds_the_setting_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The spec does not say which error comes first; whichever it is, line and setting agree."""
    db = _db(tmp_path)
    text = (
        "tables:\n  Writer:\n    props: [Name, Nope1]\n  Volume:\n    label: Nope2\n  Nope3: {}\n"
    )
    path = _settings(tmp_path, text)
    assert _import(db, path, tmp_path / "library.tessera") == 1
    err = capsys.readouterr().err
    match = re.search(re.escape(str(path)) + r":(\d+):", err)
    assert match, err
    lines = text.split("\n")
    shown = lines[int(match.group(1)) - 1]
    assert any(word in err and word in shown for word in ("Nope1", "Nope2", "Nope3")), err
    assert not (tmp_path / "library.tessera").exists()


def test_a_wrong_setting_leaves_an_existing_output_as_it_was(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _db(tmp_path)
    good = _settings(tmp_path, GOOD)
    out = tmp_path / "library.tessera"
    assert _import(db, good, out) == 0
    before = out.read_bytes()
    capsys.readouterr()
    bad = _settings(tmp_path, "tables:\n  Nope: {}\n", "bad.yaml")
    assert _import(db, bad, out) == 1
    assert "Traceback" not in capsys.readouterr().err
    assert out.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "bad.yaml",
        "library.db",
        "library.tessera",
        "settings.yaml",
    ]


def test_the_settings_file_is_named_as_it_was_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _db(tmp_path)
    _settings(tmp_path, "tables:\n  Writer: {}\n  Nope: {}\n", "rel.yaml")
    monkeypatch.chdir(tmp_path)
    assert _import("library.db", "rel.yaml", "out.tessera") == 1
    err = capsys.readouterr().err
    assert "rel.yaml:3:" in err and str(tmp_path) not in err.split("rel.yaml")[0], err
    assert not (tmp_path / "out.tessera").exists()


# --- settings files that are not settings ---------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\n\n",
        b"# only a comment\n",
        b"---\n",
        b"just words\n",
        b"42\n",
        b"- Writer\n- Volume\n",
        b"tables:\n",
        b"tables: ~\n",
        b"tables: {}\n",
        b"tables: []\n",
        b"tables: Writer\n",
        b"tables:\n  - Writer\n",
        b"tables: {Writer: 5}\n",
        b"tables: {Writer: [Name]}\n",
        b"tables: {1: {}}\n",
        b"tables: {Writer: {}}\ncolour: red\n",
        b"{Writer: {}}\n",
        b"tables:\n  Writer: {}\n---\ntables:\n  Volume: {}\n",
        b"tables: {Writer: {props: [Name,\n",
        b"tables:\n\tWriter: {}\n",
        b"tables: {Writer: {}}\x00\n",
        b"tables: {Writer: {label: \xe9}}\n",
        b"\xff\xfe\x00\x00",
    ],
    ids=[
        "empty",
        "blank-lines",
        "comment-only",
        "document-marker-only",
        "scalar",
        "number",
        "list",
        "tables-without-value",
        "tables-null",
        "tables-empty",
        "tables-empty-list",
        "tables-scalar",
        "tables-list",
        "table-is-a-number",
        "table-is-a-list",
        "table-name-is-a-number",
        "unknown-top-level-key",
        "no-tables-key",
        "two-documents",
        "unclosed-flow",
        "tab-indent",
        "nul-byte",
        "not-utf8",
        "utf-16-looking",
    ],
)
def test_a_settings_file_that_is_not_settings_is_named_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    db = _db(tmp_path)
    before = db.read_bytes()
    path = _settings(tmp_path, content)
    out = tmp_path / "library.tessera"
    err = _refused(capsys, _import(db, path, out), out, db, before)
    assert str(path) in err, err


def test_a_settings_file_that_is_a_directory_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _db(tmp_path)
    before = db.read_bytes()
    folder = tmp_path / "settings.d"
    folder.mkdir()
    out = tmp_path / "library.tessera"
    err = _refused(capsys, _import(db, folder, out), out, db, before)
    assert "settings.d" in err


def test_a_python_tag_in_the_settings_is_refused_and_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Section 10: a settings file is untrusted input."""
    db = _db(tmp_path)
    before = db.read_bytes()
    marker = tmp_path / "ran"
    path = _settings(tmp_path, f'tables: !!python/object/apply:os.mkdir ["{marker}"]\n')
    out = tmp_path / "library.tessera"
    err = _refused(capsys, _import(db, path, out), out, db, before)
    assert str(path) in err
    assert not marker.exists()
    other = _settings(tmp_path, f"tables: !!python/name:os.mkdir\nx: {marker}\n", "name.yaml")
    assert _import(db, other, out) == 1
    assert not marker.exists()
    assert "name.yaml" in capsys.readouterr().err


def test_a_settings_file_with_a_byte_order_mark_is_read_or_named_never_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _db(tmp_path)
    path = _settings(tmp_path, b"\xef\xbb\xbf" + GOOD.encode("utf-8"))
    out = tmp_path / "library.tessera"
    rc = _import(db, path, out)
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert rc in (0, 1)
    if rc == 0:
        assert out.exists()
    else:
        assert str(path) in captured.err
        assert not out.exists()


def test_the_database_given_as_the_settings_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _db(tmp_path)
    before = db.read_bytes()
    out = tmp_path / "library.tessera"
    err = _refused(capsys, _import(db, db, out), out, db, before)
    assert "library.db" in err


# --- a source that is not a SQLite database -------------------------------------------------


def test_the_settings_given_as_the_database_names_that_file_as_not_a_sqlite_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _db(tmp_path)
    path = _settings(tmp_path, GOOD)
    out = tmp_path / "library.tessera"
    assert _import(path, path, out) == 1
    err = capsys.readouterr().err
    assert "settings.yaml" in err and "not a SQLite database" in err, err
    assert not out.exists()
    assert path.read_text(encoding="utf-8") == GOOD


@pytest.mark.parametrize(
    "content",
    [
        b"\x00" * 4096,
        b"SQLite format 3\x00",
        b"PK\x03\x04" + b"\x00" * 100,
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        b"tables:\n  Writer: {}\n",
        b"SQLite format 3" + b" " * 200,
    ],
    ids=["zeros", "magic-only", "zip", "png", "text", "magic-without-nul"],
)
def test_other_files_are_named_as_not_a_sqlite_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(content)
    settings = _settings(tmp_path, GOOD)
    out = tmp_path / "out" / "source.tessera"
    assert _import(path, settings, out) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "source.bin" in captured.err and "not a SQLite database" in captured.err, captured.err
    assert "Traceback" not in captured.err
    assert not out.exists()
    assert path.read_bytes() == content


def test_a_file_that_is_not_a_database_and_wrong_settings_still_gives_one_named_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "notes.txt"
    source.write_bytes(b"not a database\n")
    path = _settings(tmp_path, "tables:\n  Nope: {}\n")
    out = tmp_path / "notes.tessera"
    assert _import(source, path, out) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "notes.txt" in captured.err or f"{path}:2:" in captured.err
    assert "Traceback" not in captured.err
    assert not out.exists()
    assert source.read_bytes() == b"not a database\n"


def test_a_database_without_the_named_tables_gives_a_named_error_for_the_first_table_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.db"
    con = sqlite3.connect(empty)
    con.execute("CREATE TABLE Other (Id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    path = _settings(tmp_path, GOOD)
    out = tmp_path / "empty.tessera"
    rc = _import(empty, path, out)
    captured = capsys.readouterr()
    assert rc == 1, captured.out
    assert f"{path}:2:" in captured.err and "Writer" in captured.err, captured.err
    assert not out.exists()


# --- success: paths, argument order, determinism --------------------------------------------


def test_names_with_spaces_and_non_ascii_letters_work_and_give_the_same_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = _db(tmp_path)
    fancy_dir = tmp_path / "bibliothèque 書"
    fancy_dir.mkdir()
    fancy = _db(fancy_dir)
    settings = _settings(tmp_path, GOOD)
    other = _settings(fancy_dir, GOOD, "réglages.yaml")
    assert _import(plain, settings, tmp_path / "a.tessera") == 0
    first = _hash(capsys.readouterr().out)
    assert _import(fancy, other, fancy_dir / "sortie 1.tessera") == 0
    assert _hash(capsys.readouterr().out) == first


def test_the_options_may_come_in_any_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _db(tmp_path)
    settings = _settings(tmp_path, GOOD)
    assert _import(db, settings, tmp_path / "a.tessera") == 0
    first = _hash(capsys.readouterr().out)
    argv = ["import", "sqlite", "-o", str(tmp_path / "b.tessera"), "--settings", str(settings)]
    assert main([*argv, str(db)]) == 0
    assert _hash(capsys.readouterr().out) == first
    argv = ["import", "sqlite", "--settings", str(settings), str(db), "-o", str(tmp_path / "c")]
    assert main(argv) == 0
    assert _hash(capsys.readouterr().out) == first


def test_the_same_settings_written_another_way_give_the_same_knowledge_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Section 4.3: the same source and settings, whatever the YAML's layout, give one hash."""
    db = _db(tmp_path)
    layouts = [
        GOOD,
        "# the library\r\ntables:\r\n  Writer:\r\n    label: Name\r\n"
        "  Volume:\r\n    label: Title\r\n",
        "tables: {Writer: {label: Name}, Volume: {label: Title}}\n",
        "tables:\n  Writer: {label: Name, summary: null, props: []}\n"
        "  Volume: {props: [], label: Title}\n",
        "tables:\n  \"Writer\":\n    label: \"Name\"\n  'Volume':\n    label: 'Title'\n",
    ]
    hashes = []
    for k, text in enumerate(layouts):
        path = _settings(tmp_path, text, f"s{k}.yaml")
        assert _import(db, path, tmp_path / f"o{k}.tessera") == 0, text
        hashes.append(_hash(capsys.readouterr().out))
    assert len(set(hashes)) == 1, hashes


def test_importing_twice_prints_the_same_knowledge_hash_on_the_installed_entry_point(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    settings = _settings(tmp_path, GOOD)
    seen = []
    for k in range(2):
        done = subprocess.run(
            [str(entry_point()), "import", "sqlite", str(db), "--settings", str(settings), "-o",
             str(tmp_path / f"{k}.tessera")],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        seen.append(_hash(done.stdout))
    assert seen[0] == seen[1]


def test_a_wrong_setting_on_the_installed_entry_point_exits_1_with_the_line(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    path = _settings(tmp_path, "tables:\n  Writer: {}\n  Nope: {}\n")
    out = tmp_path / "library.tessera"
    done = subprocess.run(
        [str(entry_point()), "import", "sqlite", str(db), "--settings", str(path), "-o", str(out)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )  # fmt: skip
    assert done.returncode == 1
    assert done.stdout == ""
    assert f"{path}:3:" in done.stderr and "Nope" in done.stderr
    assert "Traceback" not in done.stderr
    assert not out.exists()


def test_a_database_that_changes_gives_a_different_knowledge_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Section 4.1: the source row carries the hash of the source's content."""
    db = _db(tmp_path)
    settings = _settings(tmp_path, GOOD)
    assert _import(db, settings, tmp_path / "a.tessera") == 0
    first = _hash(capsys.readouterr().out)
    con = sqlite3.connect(db)
    con.execute("UPDATE Writer SET Born = '1902' WHERE WriterId = 1")
    con.commit()
    con.close()
    assert _import(db, settings, tmp_path / "b.tessera") == 0
    assert _hash(capsys.readouterr().out) != first


def test_a_tessera_made_from_a_database_has_one_source_and_is_not_a_mosaic(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    settings = _settings(tmp_path, GOOD)
    out = tmp_path / "library.tessera"
    assert _import(db, settings, out) == 0
    with open_sealed(out) as sealed:
        assert sealed.query("SELECT kind FROM header") == [("tessera",)]
        assert len(sealed.query("SELECT sid FROM source")) == 1
        assert sealed.query("SELECT count(*) FROM vector") == [(0,)]
        assert sealed.query("SELECT count(*) FROM link_count") == [(0,)]


def test_a_database_with_a_non_ascii_file_name_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _db(tmp_path, "livre écrit 書.db")
    settings = _settings(tmp_path, GOOD, "réglages 1.yaml")
    out = tmp_path / "sortie 書.tessera"
    assert _import(db, settings, out) == 0
    _hash(capsys.readouterr().out)
    assert out.exists()
