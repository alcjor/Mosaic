"""Edge cases of a table whose primary key is two foreign keys (plan M3.13; sections 3.1, 3.4,
3.5, 4.1), written from the maintainer's answer on #124 (reading 2) and the spec's words.

What test_sqlite_edge_table.py covers is not repeated: this file takes the odd values, odd
names, empty and looping tables, ordering and determinism, the source left untouched, and
the settings file.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build.cli import main
from mosaic_build.tessera.convert import Boolean
from mosaic_build.tessera.sqlite import (
    SettingError,
    Settings,
    Table,
    build,
    check_settings,
)
from mosaic_format.check import check_file

PARENTS = (
    "CREATE TABLE Writer (WriterId INTEGER PRIMARY KEY, Name TEXT, Code TEXT UNIQUE);"
    "CREATE TABLE Volume (VolumeId INTEGER PRIMARY KEY, Title TEXT);"
)
CREDIT = (
    "CREATE TABLE Credit (WriterId INTEGER REFERENCES Writer, VolumeId INTEGER REFERENCES Volume,"
    " Role TEXT, PRIMARY KEY (WriterId, VolumeId));"
)
PARENT_ROWS = (
    "INSERT INTO Writer VALUES (1, 'Ada', 'x'), (2, 'Bo', 'y');"
    "INSERT INTO Volume VALUES (10, 'Salt'), (11, 'Hours');"
)
SETTINGS = Settings(tables={"Writer": Table(), "Volume": Table(), "Credit": Table(edge="credited")})


def _database(path: Path, schema: str = PARENTS + CREDIT, rows: str = PARENT_ROWS) -> Path:
    con = sqlite3.connect(path)
    con.executescript(schema + rows)
    con.commit()
    con.close()
    return path


def _insert(path: Path, sql: str, *args: object) -> None:
    con = sqlite3.connect(path)
    con.execute(sql, args)
    con.commit()
    con.close()


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with mosaic_format.open(path) as f:
        return f.query(sql)


def _violations(path: Path) -> list[str]:
    return [str(v) for v in check_file(path).violations]


def _refused(tmp_path: Path, db: Path, settings: Settings, match: str) -> None:
    out = tmp_path / "refused.tessera"
    with pytest.raises(ValueError, match=match):
        build(db, out, settings)
    assert not out.exists()


def _locators(path: Path) -> list[str]:
    return [
        str(x) for (x,) in _rows(path, "SELECT locator FROM evidence WHERE locator LIKE '%Credit%'")
    ]


# --- empty and looping tables ---------------------------------------------------------------


def test_an_edge_table_with_no_rows_gives_no_edge_and_still_a_valid_tessera(
    tmp_path: Path,
) -> None:
    # Section 3.4: an edge type is declared; M3.1 declares the type of an empty table too.
    db = _database(tmp_path / "empty.db")
    out = tmp_path / "empty.tessera"
    build(db, out, SETTINGS)
    assert _rows(out, "SELECT count(*) FROM edge") == [(0,)]
    assert _violations(out) == []
    assert _rows(out, "SELECT from_type, to_type FROM type WHERE name = 'credited'") == [
        ("Writer", "Volume")
    ]


def test_a_row_naming_the_same_row_twice_is_one_loop_edge(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "loop.db",
        "CREATE TABLE P (Id INTEGER PRIMARY KEY);"
        "CREATE TABLE Link (A INTEGER REFERENCES P, B INTEGER REFERENCES P, PRIMARY KEY (A, B));",
        "INSERT INTO P VALUES (1); INSERT INTO Link VALUES (1, 1);",
    )
    out = tmp_path / "loop.tessera"
    build(db, out, Settings(tables={"P": Table(), "Link": Table(edge="same")}))
    assert _rows(out, "SELECT src, dst FROM v_edge") == [("P:1", "P:1")]
    assert _rows(out, "SELECT locator FROM v_evidence WHERE edge_type = 'same'") == [
        ("file=loop.db;table=Link;row=1/1",)
    ]
    assert _violations(out) == []


def test_a_foreign_key_on_a_column_outside_the_key_is_a_prop_and_gives_no_edge(
    tmp_path: Path,
) -> None:
    # "the row's other columns become the edge's props" (#124): no foreign_keys setting there.
    db = _database(
        tmp_path / "extra.db",
        PARENTS + "CREATE TABLE Press (PressId INTEGER PRIMARY KEY);"
        "CREATE TABLE Credit (WriterId INTEGER REFERENCES Writer,"
        " VolumeId INTEGER REFERENCES Volume, PressId INTEGER REFERENCES Press,"
        " PRIMARY KEY (WriterId, VolumeId));",
        PARENT_ROWS + "INSERT INTO Press VALUES (7); INSERT INTO Credit VALUES (1, 10, 7);",
    )
    out = tmp_path / "extra.tessera"
    build(db, out, Settings(tables={**SETTINGS.tables, "Press": Table()}))
    assert _rows(out, "SELECT type, src, dst, props FROM v_edge") == [
        ("credited", "Writer:1", "Volume:10", '{"PressId":7}')
    ]


# --- values -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("'a' || char(0) || 'b'", r"U\+0000"),
        ("X'00ff'", "blob"),
        ("9e999", r"'Role'"),
        ("-9e999", r"'Role'"),
        ("CAST(X'ff' AS TEXT)", r"bad\.db"),
        ("CAST(X'eda080' AS TEXT)", r"bad\.db"),
    ],
)
def test_a_prop_value_a_tessera_cannot_hold_is_refused_naming_the_database(
    tmp_path: Path, value: str, match: str
) -> None:
    # Section 3.1 (no U+0000, I-JSON numbers, UTF-8 text); same refusals as for a node table.
    db = _database(
        tmp_path / "bad.db",
        PARENTS + "CREATE TABLE Credit (WriterId INTEGER REFERENCES Writer,"
        " VolumeId INTEGER REFERENCES Volume, Role, PRIMARY KEY (WriterId, VolumeId));",
        PARENT_ROWS + f"INSERT INTO Credit VALUES (1, 10, {value});",
    )
    _refused(tmp_path, db, SETTINGS, match)


def test_prop_names_are_ordered_by_utf16_code_units_and_text_is_kept_as_written(
    tmp_path: Path,
) -> None:
    # Section 3.1: object keys sorted by UTF-16 code units: U+1F600 (D83D DE00) < U+E000.
    db = _database(
        tmp_path / "o.db",
        PARENTS + "CREATE TABLE Credit (WriterId INTEGER REFERENCES Writer,"
        ' VolumeId INTEGER REFERENCES Volume, "\U0001f600" TEXT, "z" TEXT, "\ue000" TEXT,'
        " PRIMARY KEY (WriterId, VolumeId));",
        PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'e\u0301', 'b', 'c');",
    )
    out = tmp_path / "o.tessera"
    build(db, out, SETTINGS)
    (props,) = _rows(out, "SELECT props FROM edge")[0]
    assert props == '{"z":"b","\U0001f600":"e\u0301","\ue000":"c"}'
    assert json.loads(str(props)) == {"z": "b", "\U0001f600": "e\u0301", "\ue000": "c"}
    assert _violations(out) == []


def test_a_row_with_only_null_other_columns_has_no_props(tmp_path: Path) -> None:
    db = _database(tmp_path / "n.db", rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, NULL);")
    out = tmp_path / "n.tessera"
    build(db, out, SETTINGS)
    props = _rows(out, "SELECT props FROM edge")[0][0]
    assert props in (None, "{}")  # section 3.4: props is a JSON object or NULL
    assert _violations(out) == []


def test_a_key_table_with_no_other_columns_has_edges_with_no_props(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "bare.db",
        PARENTS + "CREATE TABLE Credit (WriterId INTEGER REFERENCES Writer,"
        " VolumeId INTEGER REFERENCES Volume, PRIMARY KEY (WriterId, VolumeId));",
        PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10), (2, 11);",
    )
    out = tmp_path / "bare.tessera"
    build(db, out, SETTINGS)
    assert [p for (p,) in _rows(out, "SELECT props FROM edge")] in ([None, None], ["{}", "{}"])
    assert _rows(out, "SELECT props FROM type WHERE name = 'credited'") in ([(None,)], [("{}",)])
    assert _violations(out) == []


# --- keys ------------------------------------------------------------------------------------


def test_zero_and_negative_integer_keys_are_joined_as_decimal_text(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "neg.db",
        PARENTS + CREDIT,
        "INSERT INTO Writer VALUES (-1, 'n', 'a'), (0, 'z', 'b');"
        "INSERT INTO Volume VALUES (0, 't'), (-5, 'u');"
        "INSERT INTO Credit VALUES (-1, 0, NULL), (0, -5, NULL);",
    )
    out = tmp_path / "neg.tessera"
    build(db, out, SETTINGS)
    assert sorted(_locators(out)) == [
        "file=neg.db;table=Credit;row=-1/0",
        "file=neg.db;table=Credit;row=0/-5",
    ]
    assert _rows(out, "SELECT src, dst FROM v_edge ORDER BY src") == [
        ("Writer:-1", "Volume:0"),
        ("Writer:0", "Volume:-5"),
    ]


def test_a_real_key_is_joined_as_the_node_key_text(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "real.db",
        "CREATE TABLE R (K REAL PRIMARY KEY); CREATE TABLE S (K REAL PRIMARY KEY);"
        "CREATE TABLE L (A REAL REFERENCES R, B REAL REFERENCES S, PRIMARY KEY (A, B));",
        "INSERT INTO R VALUES (1.5); INSERT INTO S VALUES (2.0); INSERT INTO L VALUES (1.5, 2.0);",
    )
    out = tmp_path / "real.tessera"
    build(db, out, Settings(tables={"R": Table(), "S": Table(), "L": Table(edge="to")}))
    (src, dst) = _rows(out, "SELECT src, dst FROM v_edge")[0]
    (loc,) = _rows(out, "SELECT locator FROM v_evidence WHERE edge_type = 'to'")[0]
    # The edge ends are the node ids; the row is the same two keys, joined by '/'.
    assert (
        str(loc)
        == f"file=real.db;table=L;row={str(src).split(':', 1)[1]}/{str(dst).split(':', 1)[1]}"
    )
    assert _violations(out) == []


def test_unicode_keys_keep_their_bytes_in_the_row_value(tmp_path: Path) -> None:
    a, b = "Cafe\u0301 \u2603", "\U0001f600 x"  # decomposed accent, snowman, non-BMP
    db = _database(
        tmp_path / "u.db",
        "CREATE TABLE Shelf (Code TEXT PRIMARY KEY); CREATE TABLE Tag (Name TEXT PRIMARY KEY);"
        "CREATE TABLE Tagged (Code TEXT REFERENCES Shelf, Name TEXT REFERENCES Tag,"
        " PRIMARY KEY (Code, Name));",
        "",
    )
    con = sqlite3.connect(db)
    con.execute("INSERT INTO Shelf VALUES (?)", (a,))
    con.execute("INSERT INTO Tag VALUES (?)", (b,))
    con.execute("INSERT INTO Tagged VALUES (?, ?)", (a, b))
    con.commit()
    con.close()
    out = tmp_path / "u.tessera"
    build(db, out, Settings(tables={"Shelf": Table(), "Tag": Table(), "Tagged": Table(edge="t")}))
    assert _rows(out, "SELECT locator FROM v_evidence WHERE edge_type = 't'") == [
        (f"file=u.db;table=Tagged;row={a}/{b}",)
    ]
    assert _rows(out, "SELECT src, dst FROM v_edge") == [(f"Shelf:{a}", f"Tag:{b}")]


def test_keys_with_newlines_equals_signs_and_spaces_are_kept_or_refused_cleanly(
    tmp_path: Path,
) -> None:
    # Section 3.5: only ';' separates pairs; the first '=' splits a pair.
    code = " a=b\n c "
    db = _database(
        tmp_path / "odd.db",
        "CREATE TABLE Shelf (Code TEXT PRIMARY KEY); CREATE TABLE Tag (Name TEXT PRIMARY KEY);"
        "CREATE TABLE Tagged (Code TEXT REFERENCES Shelf, Name TEXT REFERENCES Tag,"
        " PRIMARY KEY (Code, Name));",
        "",
    )
    con = sqlite3.connect(db)
    con.execute("INSERT INTO Shelf VALUES (?)", (code,))
    con.execute("INSERT INTO Tag VALUES ('t')")
    con.execute("INSERT INTO Tagged VALUES (?, 't')", (code,))
    con.commit()
    con.close()
    out = tmp_path / "odd.tessera"
    settings = Settings(tables={"Shelf": Table(), "Tag": Table(), "Tagged": Table(edge="t")})
    try:
        build(db, out, settings)
    except ValueError:
        assert not out.exists()
        return
    assert _rows(out, "SELECT locator FROM v_evidence WHERE edge_type = 't'") == [
        (f"file=odd.db;table=Tagged;row={code}/t",)
    ]
    assert _violations(out) == []


def test_a_very_long_key_is_kept_whole(tmp_path: Path) -> None:
    long = "k" * 100_000
    db = _database(
        tmp_path / "long.db",
        "CREATE TABLE Shelf (Code TEXT PRIMARY KEY); CREATE TABLE Tag (Name TEXT PRIMARY KEY);"
        "CREATE TABLE Tagged (Code TEXT REFERENCES Shelf, Name TEXT REFERENCES Tag,"
        " PRIMARY KEY (Code, Name));",
        "",
    )
    con = sqlite3.connect(db)
    con.execute("INSERT INTO Shelf VALUES (?)", (long,))
    con.execute("INSERT INTO Tag VALUES ('t')")
    con.execute("INSERT INTO Tagged VALUES (?, 't')", (long,))
    con.commit()
    con.close()
    out = tmp_path / "long.tessera"
    build(db, out, Settings(tables={"Shelf": Table(), "Tag": Table(), "Tagged": Table(edge="t")}))
    assert _rows(out, "SELECT locator FROM v_evidence WHERE edge_type = 't'") == [
        (f"file=long.db;table=Tagged;row={long}/t",)
    ]


def test_a_value_that_differs_from_a_key_only_in_case_or_spaces_names_no_row(
    tmp_path: Path,
) -> None:
    for value in ("a", "A "):
        db = _database(
            tmp_path / "case.db",
            "CREATE TABLE Shelf (Code TEXT PRIMARY KEY); CREATE TABLE Tag (Name TEXT PRIMARY KEY);"
            "CREATE TABLE Tagged (Code TEXT REFERENCES Shelf, Name TEXT REFERENCES Tag,"
            " PRIMARY KEY (Code, Name));",
            f"INSERT INTO Shelf VALUES ('A'); INSERT INTO Tag VALUES ('t');"
            f"INSERT INTO Tagged VALUES ('{value}', 't');",
        )
        _refused(
            tmp_path,
            db,
            Settings(tables={"Shelf": Table(), "Tag": Table(), "Tagged": Table(edge="t")}),
            r"case\.db: table 'Tagged'",
        )
        db.unlink()


def test_key_columns_named_with_spaces_and_quotes_work(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "q.db",
        'CREATE TABLE "My Writer" ("Writer Id" INTEGER PRIMARY KEY);'
        'CREATE TABLE "Vol""ume" (V INTEGER PRIMARY KEY);'
        'CREATE TABLE "Credit Line" ("Writer Id" INTEGER REFERENCES "My Writer",'
        ' "the ""vol""" INTEGER REFERENCES "Vol""ume", "Note x" TEXT,'
        ' PRIMARY KEY ("Writer Id", "the ""vol"""));',
        'INSERT INTO "My Writer" VALUES (1); INSERT INTO "Vol""ume" VALUES (2);'
        "INSERT INTO \"Credit Line\" VALUES (1, 2, 'hi');",
    )
    out = tmp_path / "q.tessera"
    build(
        db,
        out,
        Settings(
            tables={
                "My Writer": Table(type="Writer"),
                'Vol"ume': Table(type="Volume"),
                "Credit Line": Table(edge="credited"),
            }
        ),
    )
    assert _rows(out, "SELECT src, dst, props FROM v_edge") == [
        ("Writer:1", "Volume:2", '{"Note x":"hi"}')
    ]
    assert _rows(out, "SELECT locator FROM v_evidence WHERE edge_type = 'credited'") == [
        ("file=q.db;table=Credit Line;row=1/2",)
    ]


def test_key_column_names_in_another_case_than_declared_still_make_an_edge_table(
    tmp_path: Path,
) -> None:
    # SQLite column names are case-insensitive.
    db = _database(
        tmp_path / "case.db",
        PARENTS + "CREATE TABLE Credit (WriterId INTEGER REFERENCES Writer,"
        " VolumeId INTEGER REFERENCES Volume, Role TEXT, PRIMARY KEY (volumeid, WRITERID));",
        PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'r');",
    )
    out = tmp_path / "case.tessera"
    build(db, out, SETTINGS)
    assert _rows(out, "SELECT src, dst, props FROM v_edge") == [
        ("Volume:10", "Writer:1", '{"Role":"r"}')
    ]
    assert _locators(out) == ["file=case.db;table=Credit;row=10/1"]


def test_a_table_without_rowid_gives_edges(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "wr.db",
        PARENTS + "CREATE TABLE Credit (WriterId INTEGER REFERENCES Writer,"
        " VolumeId INTEGER REFERENCES Volume, PRIMARY KEY (WriterId, VolumeId)) WITHOUT ROWID;",
        PARENT_ROWS + "INSERT INTO Credit VALUES (2, 11), (1, 10);",
    )
    out = tmp_path / "wr.tessera"
    build(db, out, SETTINGS)
    assert _rows(out, "SELECT src, dst FROM v_edge ORDER BY src") == [
        ("Writer:1", "Volume:10"),
        ("Writer:2", "Volume:11"),
    ]


def test_a_key_column_that_names_a_unique_column_gives_the_edge_to_that_row(
    tmp_path: Path,
) -> None:
    # As for a node table (M3.1): the value names the row it equals; the row value is the key
    # columns' values as written in the table.
    db = _database(
        tmp_path / "uq.db",
        PARENTS + "CREATE TABLE Credit (WCode TEXT REFERENCES Writer (Code),"
        " VolumeId INTEGER REFERENCES Volume, PRIMARY KEY (WCode, VolumeId));",
        PARENT_ROWS + "INSERT INTO Credit VALUES ('y', 10);",
    )
    out = tmp_path / "uq.tessera"
    build(db, out, SETTINGS)
    assert _rows(out, "SELECT src, dst FROM v_edge") == [("Writer:2", "Volume:10")]
    assert _locators(out) == ["file=uq.db;table=Credit;row=y/10"]


def test_a_text_value_equal_to_an_integer_key_names_that_row(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "txt.db",
        PARENTS
        + "CREATE TABLE Credit (W, V, PRIMARY KEY (W, V));"
        # untyped key columns declared as foreign keys at table level
        .replace(
            "PRIMARY KEY (W, V))",
            "PRIMARY KEY (W, V),"
            " FOREIGN KEY (W) REFERENCES Writer, FOREIGN KEY (V) REFERENCES Volume)",
        ),
        PARENT_ROWS + "INSERT INTO Credit VALUES ('1', 10.0);",
    )
    out = tmp_path / "txt.tessera"
    try:
        build(db, out, SETTINGS)
    except ValueError:
        assert not out.exists()  # a refusal naming the row is acceptable; a wrong edge is not
        return
    assert _rows(out, "SELECT src, dst FROM v_edge") == [("Writer:1", "Volume:10")]
    assert _violations(out) == []


# --- several edge tables ---------------------------------------------------------------------


def test_two_edge_tables_with_one_edge_type_name_are_refused() -> None:
    settings = Settings(tables={"Credit": Table(edge="linked"), "Other": Table(edge="linked")})
    with pytest.raises(SettingError, match=r"'linked'") as e:
        check_settings(settings)
    assert e.value.where[:1] == ("tables",)


def test_two_edge_tables_between_the_same_two_rows_keep_both_edges_and_their_evidence(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "two.db",
        PARENTS + CREDIT + "CREATE TABLE Review (WriterId INTEGER REFERENCES Writer,"
        " VolumeId INTEGER REFERENCES Volume, PRIMARY KEY (WriterId, VolumeId));",
        PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'a'); INSERT INTO Review VALUES (1, 10);",
    )
    out = tmp_path / "two.tessera"
    build(db, out, Settings(tables={**SETTINGS.tables, "Review": Table(edge="reviewed")}))
    assert _rows(out, "SELECT type, src, dst, qualifier FROM v_edge ORDER BY type") == [
        ("credited", "Writer:1", "Volume:10", ""),
        ("reviewed", "Writer:1", "Volume:10", ""),
    ]
    assert _rows(out, "SELECT locator FROM v_evidence WHERE edge_type IS NOT NULL ORDER BY 1") == [
        ("file=two.db;table=Credit;row=1/10",),
        ("file=two.db;table=Review;row=1/10",),
    ]


def test_an_edge_table_and_a_foreign_key_edge_between_the_same_rows_are_two_edges(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "mix.db",
        "CREATE TABLE Writer (WriterId INTEGER PRIMARY KEY, Fav INTEGER REFERENCES Volume);"
        "CREATE TABLE Volume (VolumeId INTEGER PRIMARY KEY);" + CREDIT.replace(", Role TEXT", ""),
        "INSERT INTO Volume VALUES (10); INSERT INTO Writer VALUES (1, 10);"
        "INSERT INTO Credit VALUES (1, 10);",
    )
    out = tmp_path / "mix.tessera"
    build(
        db,
        out,
        Settings(
            tables={
                "Writer": Table(foreign_keys={"Fav": "favours"}),
                "Volume": Table(),
                "Credit": Table(edge="credited"),
            }
        ),
    )
    assert _rows(out, "SELECT type, src, dst FROM v_edge ORDER BY type") == [
        ("credited", "Writer:1", "Volume:10"),
        ("favours", "Writer:1", "Volume:10"),
    ]


def test_convert_beside_edge_is_applied_or_refused_cleanly(tmp_path: Path) -> None:
    # The answer (#124) does not say whether `convert` applies to an edge's props.
    db = _database(tmp_path / "cv.db", rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'y');")
    settings = Settings(
        tables={
            **SETTINGS.tables,
            "Credit": Table(edge="credited", convert={"Role": Boolean(true=("y",), false=("n",))}),
        }
    )
    out = tmp_path / "cv.tessera"
    try:
        build(db, out, settings)
    except ValueError:
        assert not out.exists()
        return
    assert _rows(out, "SELECT props FROM edge") == [('{"Role":true}',)]
    assert _violations(out) == []


# --- determinism, ordering and the source ----------------------------------------------------


def test_rows_inserted_in_another_order_give_the_same_graph(tmp_path: Path) -> None:
    # The source's hash is the database's bytes, which differ; everything else must not.
    rows = [(1, 10, "a"), (1, 11, "b"), (2, 10, "c"), (2, 11, "d")]
    dumps = []
    for name, order in (("one", rows), ("two", rows[::-1])):
        folder = tmp_path / name  # the file name is in the evidence: same name, two places
        folder.mkdir()
        sql = "".join(f"INSERT INTO Credit VALUES ({w}, {v}, '{r}');" for w, v, r in order)
        db = _database(folder / "c.db", rows=PARENT_ROWS + sql)
        out = folder / "c.tessera"
        build(db, out, SETTINGS)
        dumps.append(
            [
                _rows(out, f"SELECT * FROM {t}")
                for t in ("node", "edge", "evidence", "type", "mention", "alias")
            ]
        )
    assert dumps[0] == dumps[1]


def test_the_order_the_tables_are_named_in_does_not_change_the_hash_with_an_edge_table(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path / "c.db", rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'a');")
    first = build(db, tmp_path / "1.tessera", SETTINGS)
    names = list(SETTINGS.tables)[::-1]
    second = build(
        db, tmp_path / "2.tessera", Settings(tables={n: SETTINGS.tables[n] for n in names})
    )
    assert first.knowledge_hash == second.knowledge_hash


def test_a_different_edge_type_name_gives_a_different_hash(tmp_path: Path) -> None:
    db = _database(tmp_path / "c.db", rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'a');")
    other = Settings(tables={**SETTINGS.tables, "Credit": Table(edge="wrote")})
    assert (
        build(db, tmp_path / "1.tessera", SETTINGS).knowledge_hash
        != build(db, tmp_path / "2.tessera", other).knowledge_hash
    )


def test_every_edge_cites_the_one_source_which_is_the_database_bytes(tmp_path: Path) -> None:
    db = _database(tmp_path / "c.db", rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'a');")
    out = tmp_path / "c.tessera"
    build(db, out, SETTINGS)
    assert _rows(out, "SELECT count(*), min(hash) FROM source") == [
        (1, hashlib.sha256(db.read_bytes()).hexdigest())
    ]
    assert _rows(
        out, "SELECT count(*) FROM evidence WHERE sid NOT IN (SELECT sid FROM source)"
    ) == [(0,)]
    for table in ("alias", "mention", "external_ref"):
        assert _rows(out, f"SELECT count(*) FROM {table}") == [(0,)]


def test_the_database_is_left_byte_identical_and_alone_when_it_has_an_edge_table(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "w"
    folder.mkdir()
    db = _database(folder / "c.db", rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'a');")
    before = db.read_bytes()
    build(db, tmp_path / "c.tessera", SETTINGS)
    assert db.read_bytes() == before
    assert [p.name for p in folder.iterdir()] == ["c.db"]


def test_a_late_refusal_in_an_edge_table_leaves_nothing_behind(tmp_path: Path) -> None:
    folder = tmp_path / "w"
    folder.mkdir()
    db = _database(
        folder / "late.db",
        rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'a'), (2, 11, 'b');",
    )
    _insert(db, "INSERT INTO Credit VALUES (?, ?, ?)", 1, 11, "x" + "\x00")
    with pytest.raises(ValueError, match=r"late\.db"):
        build(db, folder / "late.tessera", SETTINGS)
    assert sorted(p.name for p in folder.iterdir()) == ["late.db"]


def test_many_rows_give_one_edge_and_one_evidence_row_each(tmp_path: Path) -> None:
    n = 60
    values = "".join(f"INSERT INTO Writer VALUES ({i}, 'n', 'c{i}');" for i in range(n))
    values += "".join(f"INSERT INTO Volume VALUES ({i}, 't');" for i in range(n))
    values += "".join(
        f"INSERT INTO Credit VALUES ({i}, {j}, NULL);" for i in range(n) for j in range(n)
    )
    db = _database(tmp_path / "big.db", rows=values)
    out = tmp_path / "big.tessera"
    build(db, out, SETTINGS)
    assert _rows(out, "SELECT count(*) FROM edge") == [(n * n,)]
    assert _rows(out, "SELECT count(*) FROM evidence WHERE eid IS NOT NULL") == [(n * n,)]
    assert _rows(out, "SELECT count(DISTINCT locator) FROM evidence WHERE eid IS NOT NULL") == [
        (n * n,)
    ]
    assert _violations(out) == []


# --- the settings file and the command ---------------------------------------------------------

FILE = "tables:\n  Writer: {}\n  Volume: {}\n  Credit:\n    edge: VALUE\n"


def _import(tmp_path: Path, settings_text: str, db: Path | None = None) -> tuple[int, Path]:
    db = db or _database(
        tmp_path / "c.db", rows=PARENT_ROWS + "INSERT INTO Credit VALUES (1, 10, 'a');"
    )
    settings = tmp_path / "s.yaml"
    settings.write_text(settings_text, encoding="utf-8")
    out = tmp_path / "out" / "c.tessera"
    return main(["import", "sqlite", str(db), "--settings", str(settings), "-o", str(out)]), out


@pytest.mark.parametrize("value", ["5", "true", "[a]", "{a: b}", "''", "Credited", "a-b"])
def test_an_edge_that_is_no_edge_type_name_in_the_file_names_file_line_and_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    rc, out = _import(tmp_path, FILE.replace("VALUE", value))
    assert rc == 1
    err = capsys.readouterr().err
    assert "s.yaml:5" in err and "edge" in err
    assert not out.parent.exists()


def test_an_edge_left_empty_in_the_file_is_the_same_as_no_edge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _import(tmp_path, FILE.replace("VALUE", ""))
    assert rc == 1
    assert "s.yaml" in capsys.readouterr().err
    assert not out.parent.exists()


def test_the_command_refuses_a_slash_in_a_key_with_exit_1_naming_table_and_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _database(
        tmp_path / "s.db",
        "CREATE TABLE Shelf (Code PRIMARY KEY); CREATE TABLE Tag (Name PRIMARY KEY);"
        "CREATE TABLE Tagged (Code REFERENCES Shelf, Name REFERENCES Tag,"
        " PRIMARY KEY (Code, Name));",
        "INSERT INTO Shelf VALUES ('A/1'); INSERT INTO Tag VALUES ('t');"
        " INSERT INTO Tagged VALUES ('A/1', 't');",
    )
    rc, out = _import(tmp_path, "tables:\n  Shelf: {}\n  Tag: {}\n  Tagged:\n    edge: t\n", db)
    err = capsys.readouterr().err
    assert rc == 1
    assert "Tagged" in err and "s.db" in err
    assert not out.parent.exists()


def test_the_command_still_refuses_a_key_of_three_columns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _database(
        tmp_path / "t.db",
        "CREATE TABLE W (Id INTEGER PRIMARY KEY);"
        "CREATE TABLE T (A INTEGER REFERENCES W, B INTEGER REFERENCES W, C INTEGER REFERENCES W,"
        " PRIMARY KEY (A, B, C));",
        "",
    )
    rc, out = _import(tmp_path, "tables:\n  W: {}\n  T:\n    edge: t\n", db)
    assert rc == 1
    err = capsys.readouterr().err
    assert "T" in err and "3 columns" in err
    assert not out.parent.exists()


def test_the_command_writes_the_same_tessera_hash_twice(tmp_path: Path) -> None:
    rc, out = _import(tmp_path, FILE.replace("VALUE", "credited"))
    assert rc == 0
    out2 = tmp_path / "again.tessera"
    rc = main(
        ["import", "sqlite", str(tmp_path / "c.db"), "--settings", str(tmp_path / "s.yaml"),
         "-o", str(out2)]
    )  # fmt: skip
    assert rc == 0
    with mosaic_format.open(out) as a, mosaic_format.open(out2) as b:
        assert a.knowledge_hash == b.knowledge_hash
