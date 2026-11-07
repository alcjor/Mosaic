"""A table whose primary key is two foreign keys gives edges (plan M3.13; sections 3.4, 3.5, 4.1).

The maintainer's answer on #124 (reading 2): such a table gives no node. Each row gives one
edge, from the row named by the first key column to the row named by the second. The table's
entry in the settings names the edge type, and the row's other columns are the edge's props.
The evidence locator is ``file=<name>;table=<table>;row=<first>/<second>``, with no ``field``.
A key of several columns that is not exactly two foreign keys is still refused, and so is a key
value that holds ``/``.
"""

import json
import re
import sqlite3
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build import __version__
from mosaic_build.cli import main
from mosaic_build.tessera.sqlite import SettingError, Settings, Table, build, check_settings
from mosaic_format.check import check_file

PRODUCER = f"mosaic-sqlite/{__version__}"

SCHEMA = """
CREATE TABLE Writer (WriterId INTEGER PRIMARY KEY, Name TEXT NOT NULL);
CREATE TABLE Volume (VolumeId INTEGER PRIMARY KEY, Title TEXT NOT NULL);
CREATE TABLE Credit (
    WriterId INTEGER NOT NULL REFERENCES Writer (WriterId),
    VolumeId INTEGER NOT NULL REFERENCES Volume (VolumeId),
    Role     TEXT,
    Share    REAL,
    PRIMARY KEY (WriterId, VolumeId)
);
"""

ROWS = """
INSERT INTO Writer VALUES (1, 'Ada Quill'), (2, 'Bo Lark');
INSERT INTO Volume VALUES (10, 'Salt Roads'), (11, 'Quiet Hours');
INSERT INTO Credit VALUES (1, 10, 'author', 0.5), (2, 10, 'editor', NULL), (2, 11, NULL, 1.0);
"""

SETTINGS = Settings(
    tables={
        "Writer": Table(label="Name"),
        "Volume": Table(label="Title"),
        "Credit": Table(edge="credited"),
    }
)


def _database(path: Path, schema: str = SCHEMA, rows: str = ROWS) -> Path:
    con = sqlite3.connect(path)
    con.executescript(schema + rows)
    con.commit()
    con.close()
    return path


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with mosaic_format.open(path) as f:
        return f.query(sql)


@pytest.fixture
def built(tmp_path: Path) -> Path:
    db = _database(tmp_path / "credits.db")
    out = tmp_path / "credits.tessera"
    build(db, out, SETTINGS)
    return out


def _refused(tmp_path: Path, db: Path, settings: Settings, match: str) -> None:
    out = tmp_path / "refused.tessera"
    with pytest.raises(ValueError, match=match):
        build(db, out, settings)
    assert not out.exists()


# --- what the table gives -------------------------------------------------------------------


def test_each_row_is_one_edge_from_the_first_key_columns_row_to_the_seconds(built: Path) -> None:
    edges = _rows(built, "SELECT type, src, dst, qualifier, props FROM v_edge ORDER BY src, dst")
    assert edges == [
        ("credited", "Writer:1", "Volume:10", "", '{"Role":"author","Share":0.5}'),
        ("credited", "Writer:2", "Volume:10", "", '{"Role":"editor"}'),
        ("credited", "Writer:2", "Volume:11", "", '{"Share":1}'),
    ]


def test_the_table_gives_no_node_and_no_node_type(built: Path) -> None:
    assert _rows(built, "SELECT id FROM node ORDER BY id") == [
        ("Volume:10",),
        ("Volume:11",),
        ("Writer:1",),
        ("Writer:2",),
    ]
    assert _rows(built, "SELECT count(*) FROM type WHERE name = 'Credit'") == [(0,)]


def test_the_edge_type_joins_the_two_tables_types_and_declares_the_other_columns(
    built: Path,
) -> None:
    assert _rows(
        built, "SELECT kind, key_prop, from_type, to_type, props FROM type WHERE name = 'credited'"
    ) == [("edge", None, "Writer", "Volume", '{"Role":"text","Share":"number"}')]


def test_each_edge_has_one_evidence_row_naming_the_table_and_the_row_with_no_field(
    built: Path,
) -> None:
    evidence = _rows(
        built,
        "SELECT edge_src, edge_dst, locator, method, producer, confidence, prop FROM v_evidence"
        " WHERE edge_type = 'credited' ORDER BY edge_src, edge_dst",
    )
    assert evidence == [
        ("Writer:1", "Volume:10", "file=credits.db;table=Credit;row=1/10", "extracted",
         PRODUCER, None, None),
        ("Writer:2", "Volume:10", "file=credits.db;table=Credit;row=2/10", "extracted",
         PRODUCER, None, None),
        ("Writer:2", "Volume:11", "file=credits.db;table=Credit;row=2/11", "extracted",
         PRODUCER, None, None),
    ]  # fmt: skip


def test_the_tessera_passes_the_checker(built: Path) -> None:
    assert [str(v) for v in check_file(built).violations] == []


def test_the_direction_follows_the_key_order_not_the_column_order(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "reversed.db",
        SCHEMA.replace("PRIMARY KEY (WriterId, VolumeId)", "PRIMARY KEY (VolumeId, WriterId)"),
    )
    out = tmp_path / "reversed.tessera"
    build(db, out, SETTINGS)
    assert _rows(out, "SELECT from_type, to_type FROM type WHERE name = 'credited'") == [
        ("Volume", "Writer")
    ]
    assert _rows(out, "SELECT src, dst FROM v_edge ORDER BY src, dst") == [
        ("Volume:10", "Writer:1"),
        ("Volume:10", "Writer:2"),
        ("Volume:11", "Writer:2"),
    ]
    assert _rows(
        out, "SELECT locator FROM v_evidence WHERE locator LIKE '%Credit%' ORDER BY 1"
    ) == [
        ("file=reversed.db;table=Credit;row=10/1",),
        ("file=reversed.db;table=Credit;row=10/2",),
        ("file=reversed.db;table=Credit;row=11/2",),
    ]


def test_both_key_columns_may_reference_the_same_table(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "pairs.db",
        "CREATE TABLE Writer (WriterId INTEGER PRIMARY KEY);"
        "CREATE TABLE Knows (A INTEGER REFERENCES Writer, B INTEGER REFERENCES Writer,"
        " PRIMARY KEY (A, B));",
        "INSERT INTO Writer VALUES (1), (2); INSERT INTO Knows VALUES (1, 2), (2, 1);",
    )
    out = tmp_path / "pairs.tessera"
    build(db, out, Settings(tables={"Writer": Table(), "Knows": Table(edge="knows")}))
    assert _rows(out, "SELECT src, dst FROM v_edge ORDER BY src") == [
        ("Writer:1", "Writer:2"),
        ("Writer:2", "Writer:1"),
    ]


def test_text_keys_are_joined_as_written(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "text.db",
        "CREATE TABLE Shelf (Code TEXT PRIMARY KEY); CREATE TABLE Tag (Name TEXT PRIMARY KEY);"
        "CREATE TABLE Tagged (Code TEXT REFERENCES Shelf, Name TEXT REFERENCES Tag,"
        " PRIMARY KEY (Code, Name));",
        "INSERT INTO Shelf VALUES ('A 1'); INSERT INTO Tag VALUES ('old');"
        "INSERT INTO Tagged VALUES ('A 1', 'old');",
    )
    out = tmp_path / "text.tessera"
    build(db, out, Settings(tables={"Shelf": Table(), "Tag": Table(), "Tagged": Table(edge="t")}))
    assert _rows(out, "SELECT src, dst FROM v_edge") == [("Shelf:A 1", "Tag:old")]
    assert _rows(out, "SELECT locator FROM v_evidence WHERE locator LIKE '%Tagged%'") == [
        ("file=text.db;table=Tagged;row=A 1/old",)
    ]


def test_the_settings_record_the_edge_and_the_same_input_gives_the_same_hash(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path / "credits.db")
    first = build(db, tmp_path / "one.tessera", SETTINGS)
    second = build(db, tmp_path / "two.tessera", SETTINGS)
    assert first.knowledge_hash == second.knowledge_hash
    (settings,) = _rows(first.path, "SELECT settings FROM header")[0]
    assert json.loads(str(settings))["tables"]["Credit"] == {"edge": "credited"}


# --- what is refused ------------------------------------------------------------------------


def test_a_key_value_holding_a_slash_is_refused_naming_the_table(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "slash.db",
        "CREATE TABLE Shelf (Code TEXT PRIMARY KEY); CREATE TABLE Tag (Name TEXT PRIMARY KEY);"
        "CREATE TABLE Tagged (Code TEXT REFERENCES Shelf, Name TEXT REFERENCES Tag,"
        " PRIMARY KEY (Code, Name));",
        "INSERT INTO Shelf VALUES ('A/1'); INSERT INTO Tag VALUES ('old');"
        "INSERT INTO Tagged VALUES ('A/1', 'old');",
    )
    settings = Settings(tables={"Shelf": Table(), "Tag": Table(), "Tagged": Table(edge="t")})
    _refused(tmp_path, db, settings, r"slash\.db: table 'Tagged'.*'A/1'.*'/'")


@pytest.mark.parametrize(
    ("value", "match"),
    [("NULL", "NULL"), ("''", "empty"), ("'a;b'", "';'")],
)
def test_a_key_value_no_locator_can_hold_is_refused(tmp_path: Path, value: str, match: str) -> None:
    db = _database(
        tmp_path / "bad.db",
        "CREATE TABLE Shelf (Code TEXT PRIMARY KEY); CREATE TABLE Tag (Name TEXT PRIMARY KEY);"
        "CREATE TABLE Tagged (Code TEXT REFERENCES Shelf, Name TEXT REFERENCES Tag,"
        " PRIMARY KEY (Code, Name));",
        "INSERT INTO Shelf VALUES ('ok'); INSERT INTO Tag VALUES ('old');"
        f"INSERT INTO Tagged VALUES ({value}, 'old');",
    )
    settings = Settings(tables={"Shelf": Table(), "Tag": Table(), "Tagged": Table(edge="t")})
    _refused(tmp_path, db, settings, rf"bad\.db: table 'Tagged'.*{match}")


def test_a_value_that_names_no_row_is_refused_naming_the_row_and_the_column(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "dangling.db", rows=ROWS + "INSERT INTO Credit VALUES (1, 99, NULL, NULL);"
    )
    _refused(tmp_path, db, SETTINGS, r"dangling\.db: table 'Credit' row 1/99: 'VolumeId'.*99")


def test_two_rows_that_name_the_same_two_rows_are_refused(tmp_path: Path) -> None:
    # Untyped key columns keep 1 and ' 1' apart; a join compares both equal to Writer 1.
    db = _database(
        tmp_path / "twice.db",
        "CREATE TABLE Writer (WriterId INTEGER PRIMARY KEY);"
        "CREATE TABLE Volume (VolumeId INTEGER PRIMARY KEY);"
        "CREATE TABLE Credit (W REFERENCES Writer, V REFERENCES Volume, PRIMARY KEY (W, V));",
        "INSERT INTO Writer VALUES (1); INSERT INTO Volume VALUES (10);"
        "INSERT INTO Credit VALUES (1, 10), (' 1', 10);",
    )
    settings = Settings({"Writer": Table(), "Volume": Table(), "Credit": Table(edge="credited")})
    _refused(tmp_path, db, settings, r"twice\.db: table 'Credit'.*both name Writer:1 and Volume:10")


@pytest.mark.parametrize(
    ("schema", "columns"),
    [
        # two columns, one of them no foreign key
        ("CREATE TABLE W (Id INTEGER PRIMARY KEY);"
         "CREATE TABLE T (A INTEGER REFERENCES W, B INTEGER, PRIMARY KEY (A, B));", 2),
        # three columns, each a foreign key
        ("CREATE TABLE W (Id INTEGER PRIMARY KEY);"
         "CREATE TABLE T (A INTEGER REFERENCES W, B INTEGER REFERENCES W,"
         " C INTEGER REFERENCES W, PRIMARY KEY (A, B, C));", 3),
        # two columns that are one foreign key of two columns
        ("CREATE TABLE W (X INTEGER, Y INTEGER, PRIMARY KEY (X, Y));"
         "CREATE TABLE T (A INTEGER, B INTEGER, PRIMARY KEY (A, B),"
         " FOREIGN KEY (A, B) REFERENCES W (X, Y));", 2),
        # two columns with no foreign key at all
        ("CREATE TABLE W (Id INTEGER PRIMARY KEY);"
         "CREATE TABLE T (A INTEGER, B INTEGER, PRIMARY KEY (A, B));", 2),
    ],
)  # fmt: skip
def test_a_key_of_several_columns_that_is_not_two_foreign_keys_is_still_refused(
    tmp_path: Path, schema: str, columns: int
) -> None:
    db = _database(tmp_path / "keys.db", schema, "")
    for t in (Table(), Table(edge="t")):
        _refused(
            tmp_path,
            db,
            Settings(tables={"W": Table(), "T": t}) if "W (Id" in schema else Settings({"T": t}),
            rf"keys\.db: table 'T'.*{columns} columns",
        )


def test_a_table_of_two_foreign_keys_without_an_edge_setting_names_the_setting(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path / "credits.db")
    settings = Settings(tables={"Writer": Table(), "Volume": Table(), "Credit": Table()})
    with pytest.raises(SettingError, match=r"credits\.db: table 'Credit'.*edge") as e:
        build(db, tmp_path / "x.tessera", settings)
    assert e.value.where == ("tables", "Credit")


def test_an_edge_setting_on_a_table_whose_key_is_one_column_names_the_setting(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path / "credits.db")
    settings = Settings(
        tables={"Writer": Table(edge="w"), "Volume": Table(), "Credit": Table(edge="c")}
    )
    with pytest.raises(SettingError, match=r"credits\.db: table 'Writer'.*one column") as e:
        build(db, tmp_path / "x.tessera", settings)
    assert e.value.where == ("tables", "Writer", "edge")


def test_a_key_column_whose_table_the_settings_do_not_name_is_refused(tmp_path: Path) -> None:
    db = _database(tmp_path / "credits.db")
    settings = Settings(tables={"Writer": Table(), "Credit": Table(edge="credited")})
    with pytest.raises(SettingError, match=r"'VolumeId'.*'Volume'.*do not name") as e:
        build(db, tmp_path / "x.tessera", settings)
    assert e.value.where == ("tables", "Credit")


def test_a_foreign_key_to_a_table_that_gives_edges_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "chain.db",
        SCHEMA + "CREATE TABLE Note (Id INTEGER PRIMARY KEY, W INTEGER, V INTEGER,"
        " FOREIGN KEY (W) REFERENCES Credit (WriterId));",
    )
    settings = Settings(tables={**SETTINGS.tables, "Note": Table(foreign_keys={"W": "on_credit"})})
    with pytest.raises(SettingError, match=r"'Note'.*'W'.*'Credit'.*edges") as e:
        build(db, tmp_path / "x.tessera", settings)
    assert e.value.where == ("tables", "Note", "foreign_keys", "W")


@pytest.mark.parametrize(
    ("table", "setting"),
    [
        (Table(edge="e", type="Credit"), "type"),
        (Table(edge="e", label="Role"), "label"),
        (Table(edge="e", summary="Role"), "summary"),
        (Table(edge="e", props=("Role",)), "props"),
        (Table(edge="e", foreign_keys={"WriterId": "w"}), "foreign_keys"),
    ],
)
def test_an_edge_table_takes_no_node_settings(table: Table, setting: str) -> None:
    with pytest.raises(SettingError, match=rf"tables\.Credit.*{setting}") as e:
        check_settings(Settings(tables={"Credit": table}))
    assert e.value.where == ("tables", "Credit", setting)


@pytest.mark.parametrize("edge", ["Credited", "", "1st", "with space"])
def test_an_edge_setting_that_is_no_edge_type_name_is_refused(edge: str) -> None:
    with pytest.raises(SettingError, match=r"tables\.Credit\.edge.*edge type name") as e:
        check_settings(Settings(tables={"Credit": Table(edge=edge)}))
    assert e.value.where == ("tables", "Credit", "edge")


def test_an_edge_type_named_twice_is_refused() -> None:
    settings = Settings(
        tables={
            "Volume": Table(foreign_keys={"WriterId": "credited"}),
            "Credit": Table(edge="credited"),
        }
    )
    with pytest.raises(SettingError, match=r"tables\.Credit\.edge.*'credited'.*already") as e:
        check_settings(settings)
    assert e.value.where == ("tables", "Credit", "edge")


# --- through the settings file and the CLI (plan M3.2) ---------------------------------------

SETTINGS_FILE = """\
tables:
  Writer:
    label: Name
  Volume:
    label: Title
  Credit:
    edge: credited
"""


def _import(tmp_path: Path, text: str) -> tuple[int, Path]:
    db = _database(tmp_path / "credits.db")
    settings = tmp_path / "settings.yaml"
    settings.write_text(text, encoding="utf-8")
    out = tmp_path / "out" / "credits.tessera"
    rc = main(["import", "sqlite", str(db), "--settings", str(settings), "-o", str(out)])
    return rc, out


def test_mosaic_import_reads_the_edge_setting_from_the_settings_file(tmp_path: Path) -> None:
    rc, out = _import(tmp_path, SETTINGS_FILE)
    assert rc == 0
    assert _rows(out, "SELECT type, src, dst FROM v_edge ORDER BY src, dst") == [
        ("credited", "Writer:1", "Volume:10"),
        ("credited", "Writer:2", "Volume:10"),
        ("credited", "Writer:2", "Volume:11"),
    ]
    direct = build(tmp_path / "credits.db", tmp_path / "direct.tessera", SETTINGS)
    with mosaic_format.open(out) as f:
        assert f.knowledge_hash == direct.knowledge_hash


def test_a_missing_edge_setting_names_the_settings_file_and_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _import(tmp_path, SETTINGS_FILE.replace("    edge: credited\n", "    {}\n"))
    assert rc == 1
    assert re.search(r"settings\.yaml:6: .*table 'Credit'.*edge", capsys.readouterr().err)
    assert not out.parent.exists()


def test_a_node_setting_beside_edge_names_the_settings_file_and_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _import(tmp_path, SETTINGS_FILE + "    label: Role\n")
    assert rc == 1
    assert re.search(r"settings\.yaml:8: .*tables\.Credit\.label", capsys.readouterr().err)
    assert not out.parent.exists()


def test_import_sqlite_help_documents_a_table_of_two_foreign_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["import", "sqlite", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "primary key is two foreign keys takes edge alone" in text
    assert "from the row its first key column names to the row its second names" in text
