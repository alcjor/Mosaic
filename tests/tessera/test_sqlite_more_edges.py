"""More edge cases of the SQLite tessera builder (plan M3.1; Specification 0.1 sections 3.1, 3.2,
3.4, 3.5, 4.1 and 4.3), written from the spec's words and the builder's documented interface.
Round 2: what test_sqlite.py and test_sqlite_edges.py do not cover.
"""

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build.tessera.sqlite import Settings, Table, build
from mosaic_format.check import check_file


def _database(path: Path, schema: str, rows: str = "") -> Path:
    con = sqlite3.connect(path)
    con.executescript(schema + rows)
    con.commit()
    con.close()
    return path


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


def _valid_or_refused(tmp_path: Path, db: Path, settings: Settings) -> Path | None:
    """A build either gives a valid tessera or refuses cleanly; never a broken file."""
    out = tmp_path / "either.tessera"
    try:
        build(db, out, settings)
    except ValueError:
        assert not out.exists()
        return None
    assert _violations(out) == []
    return out


PARENT = "CREATE TABLE P (Id INTEGER PRIMARY KEY);INSERT INTO P VALUES (1), (2);"


# --- the locator is ';'-separated (section 3.5): no name in it may break it ----------------


def test_a_table_name_holding_a_semicolon_does_not_break_the_locator(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "t.db",
        'CREATE TABLE "a;row=9" (K INTEGER PRIMARY KEY);',
        'INSERT INTO "a;row=9" VALUES (1);',
    )
    out = _valid_or_refused(tmp_path, db, Settings(tables={"a;row=9": Table(type="T")}))
    if out is not None:
        for (loc,) in _rows(out, "SELECT locator FROM evidence"):
            pairs = str(loc).split(";")
            assert all("=" in p for p in pairs), loc
            assert [p.split("=", 1)[0] for p in pairs].count("row") == 1, loc


def test_a_foreign_key_column_holding_a_semicolon_does_not_break_the_locator(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "c.db",
        PARENT + 'CREATE TABLE C (Id INTEGER PRIMARY KEY, "x;y=z" INTEGER REFERENCES P);',
        "INSERT INTO C VALUES (5, 1);",
    )
    out = _valid_or_refused(
        tmp_path, db, Settings(tables={"P": Table(), "C": Table(foreign_keys={"x;y=z": "of"})})
    )
    if out is not None:
        for (loc,) in _rows(out, "SELECT locator FROM evidence"):
            assert all("=" in p for p in str(loc).split(";")), loc


def test_a_file_name_holding_a_semicolon_does_not_break_the_locator(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "a;table=Z.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY);",
        "INSERT INTO T VALUES (1);",
    )
    out = _valid_or_refused(tmp_path, db, Settings(tables={"T": Table()}))
    if out is not None:
        for (loc,) in _rows(out, "SELECT locator FROM evidence"):
            names = [p.split("=", 1)[0] for p in str(loc).split(";")]
            assert names.count("table") == 1, loc


# --- which "tables" the settings may name (section 4.1: tables only) -----------------------


def test_a_view_named_in_the_settings_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "v.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY);CREATE VIEW W AS SELECT K FROM T;",
        "INSERT INTO T VALUES (1);",
    )
    _refused(tmp_path, db, Settings(tables={"W": Table()}), r"v\.db.*'W'")


def test_an_internal_table_named_in_the_settings_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "s.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY AUTOINCREMENT);",
        "INSERT INTO T VALUES (1);",
    )
    _refused(tmp_path, db, Settings(tables={"sqlite_sequence": Table(type="Seq")}), r"s\.db")


def test_a_virtual_table_named_in_the_settings_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "f.db"
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE VIRTUAL TABLE F USING fts5(body)")
    except sqlite3.OperationalError:
        pytest.skip("this SQLite has no FTS5")
    con.execute("INSERT INTO F VALUES ('x')")
    con.commit()
    con.close()
    _refused(tmp_path, db, Settings(tables={"F": Table(props=("body",))}), r"f\.db.*'F'")


# --- keys that SQLite keeps apart but the text key would merge (sections 3.4, 4.1) ---------


def test_integer_one_and_text_one_in_an_untyped_key_column_are_two_rows_with_one_key(
    tmp_path: Path,
) -> None:
    # SQLite keeps 1 and '1' apart in a column with no affinity; as text keys they are equal and
    # (type, key) is unique, so the builder must refuse (the docs: "two rows with the same key").
    db = _database(
        tmp_path / "dup.db",
        "CREATE TABLE T (K PRIMARY KEY);",
        "INSERT INTO T VALUES (1), ('1');",
    )
    assert _valid_or_refused(tmp_path, db, Settings(tables={"T": Table()})) is None


def test_a_very_long_key_is_kept_whole(tmp_path: Path) -> None:
    key = "k" * 20_000
    db = _database(
        tmp_path / "longkey.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY);",
        f"INSERT INTO T VALUES ('{key}');",
    )
    out = _valid_or_refused(tmp_path, db, Settings(tables={"T": Table()}))
    if out is not None:
        assert _rows(out, "SELECT id FROM node") == [(f"T:{key}",)]


def test_a_key_with_newlines_and_control_characters_is_kept(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "ctl.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY);",
        "INSERT INTO T VALUES ('a' || char(10) || 'b'), ('t' || char(9)), ('d' || char(127));",
    )
    out = _valid_or_refused(tmp_path, db, Settings(tables={"T": Table()}))
    if out is not None:
        assert {k for (k,) in _rows(out, "SELECT key FROM node")} == {"a\nb", "t\t", "d\x7f"}


# --- foreign keys (section 4.1) ------------------------------------------------------------


def test_a_text_foreign_key_value_names_the_integer_key_it_equals_in_a_join(
    tmp_path: Path,
) -> None:
    # The docs: values are "compared as SQLite compares them in a join" (column affinity).
    db = _database(
        tmp_path / "aff.db",
        PARENT + "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId TEXT REFERENCES P);",
        "INSERT INTO C VALUES (5, '2');",
    )
    out = tmp_path / "aff.tessera"
    build(db, out, Settings(tables={"P": Table(), "C": Table(foreign_keys={"PId": "in_p"})}))
    assert _rows(
        out,
        "SELECT s.id, d.id FROM edge e JOIN node s ON s.nid = e.src JOIN node d ON d.nid = e.dst",
    ) == [("C:5", "P:2")]
    assert _violations(out) == []


def test_a_foreign_key_naming_a_row_with_a_text_key_keeps_case(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "case.db",
        "CREATE TABLE P (Id TEXT PRIMARY KEY);INSERT INTO P VALUES ('a'), ('A');"
        "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId TEXT REFERENCES P);",
        "INSERT INTO C VALUES (1, 'A'), (2, 'a');",
    )
    out = tmp_path / "case.tessera"
    build(db, out, Settings(tables={"P": Table(), "C": Table(foreign_keys={"PId": "in_p"})}))
    assert sorted(
        _rows(
            out,
            "SELECT s.id, d.id FROM edge e"
            " JOIN node s ON s.nid = e.src JOIN node d ON d.nid = e.dst",
        )
    ) == [("C:1", "P:A"), ("C:2", "P:a")]


def test_a_primary_key_that_is_also_a_foreign_key_is_an_edge_to_the_same_key(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "ext.db",
        PARENT + "CREATE TABLE Ext (Id INTEGER PRIMARY KEY REFERENCES P (Id), Note TEXT);",
        "INSERT INTO Ext VALUES (2, 'n');",
    )
    out = tmp_path / "ext.tessera"
    build(
        db,
        out,
        Settings(
            tables={"P": Table(), "Ext": Table(props=("Note",), foreign_keys={"Id": "extends"})}
        ),
    )
    assert _rows(
        out,
        "SELECT s.id, d.id FROM edge e JOIN node s ON s.nid = e.src JOIN node d ON d.nid = e.dst",
    ) == [("Ext:2", "P:2")]
    assert _violations(out) == []


def test_a_foreign_key_of_a_column_with_only_null_still_declares_its_edge_type(
    tmp_path: Path,
) -> None:
    # Docs: a foreign key the settings name "gives one edge type"; no edge needs to exist.
    db = _database(
        tmp_path / "nulls.db",
        PARENT + "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId INTEGER REFERENCES P);",
        "INSERT INTO C VALUES (1, NULL), (2, NULL);",
    )
    out = tmp_path / "nulls.tessera"
    build(db, out, Settings(tables={"P": Table(), "C": Table(foreign_keys={"PId": "in_p"})}))
    assert _rows(out, "SELECT count(*) FROM edge") == [(0,)]
    assert _rows(out, "SELECT name, from_type, to_type FROM type WHERE kind = 'edge'") == [
        ("in_p", "C", "P")
    ]
    assert _violations(out) == []


def test_two_columns_to_one_table_with_different_edge_names_give_two_edges(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "two.db",
        PARENT + "CREATE TABLE C (Id INTEGER PRIMARY KEY,"
        " A INTEGER REFERENCES P, B INTEGER REFERENCES P);",
        "INSERT INTO C VALUES (5, 1, 2);",
    )
    out = tmp_path / "two.tessera"
    build(
        db,
        out,
        Settings(tables={"P": Table(), "C": Table(foreign_keys={"A": "first", "B": "second"})}),
    )
    assert sorted(
        _rows(
            out,
            "SELECT e.type, d.id FROM edge e JOIN node d ON d.nid = e.dst",
        )
    ) == [("first", "P:1"), ("second", "P:2")]
    assert _violations(out) == []


def test_two_child_tables_sharing_an_edge_name_are_valid_or_refused(tmp_path: Path) -> None:
    # Section 3.4: an edge type is declared once with one (from_type, to_type).
    db = _database(
        tmp_path / "share.db",
        PARENT + "CREATE TABLE C1 (Id INTEGER PRIMARY KEY, PId INTEGER REFERENCES P);"
        "CREATE TABLE C2 (Id INTEGER PRIMARY KEY, PId INTEGER REFERENCES P);",
        "INSERT INTO C1 VALUES (1, 1); INSERT INTO C2 VALUES (1, 1);",
    )
    _valid_or_refused(
        tmp_path,
        db,
        Settings(
            tables={
                "P": Table(),
                "C1": Table(type="CA", foreign_keys={"PId": "in_p"}),
                "C2": Table(type="CB", foreign_keys={"PId": "in_p"}),
            }
        ),
    )


def test_a_composite_foreign_key_is_refused_naming_the_column(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "comp.db",
        "CREATE TABLE P (A INTEGER, B INTEGER, PRIMARY KEY (A, B));"
        "CREATE TABLE C (Id INTEGER PRIMARY KEY, A INTEGER, B INTEGER,"
        " FOREIGN KEY (A, B) REFERENCES P (A, B));",
        "",
    )
    _refused(
        tmp_path,
        db,
        Settings(tables={"C": Table(foreign_keys={"A": "in_p"})}),
        r"comp\.db.*(?:'A'|'C'|'P')",
    )


def test_a_column_with_two_foreign_keys_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "dbl.db",
        "CREATE TABLE P (Id INTEGER PRIMARY KEY);CREATE TABLE Q (Id INTEGER PRIMARY KEY);"
        "CREATE TABLE C (Id INTEGER PRIMARY KEY, X INTEGER REFERENCES P,"
        " FOREIGN KEY (X) REFERENCES Q (Id));",
    )
    _refused(
        tmp_path,
        db,
        Settings(tables={"P": Table(), "Q": Table(), "C": Table(foreign_keys={"X": "in"})}),
        r"dbl\.db.*'X'",
    )


def test_a_foreign_key_value_naming_a_real_that_equals_the_key_is_one_edge(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "real.db",
        PARENT + "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId REAL REFERENCES P);",
        "INSERT INTO C VALUES (1, 2.0);",
    )
    out = tmp_path / "real.tessera"
    build(db, out, Settings(tables={"P": Table(), "C": Table(foreign_keys={"PId": "in_p"})}))
    assert _rows(out, "SELECT d.id FROM edge e JOIN node d ON d.nid = e.dst") == [("P:2",)]


# --- props, labels, settings that repeat or overlap ----------------------------------------


def test_a_column_named_twice_in_props_is_valid_or_refused(tmp_path: Path) -> None:
    # Section 3.1 (I-JSON): no duplicate object keys.
    db = _database(
        tmp_path / "d.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V TEXT);",
        "INSERT INTO T VALUES (1, 'x');",
    )
    out = _valid_or_refused(tmp_path, db, Settings(tables={"T": Table(props=("V", "V"))}))
    if out is not None:
        assert _rows(out, "SELECT props FROM node") == [('{"V":"x"}',)]


def test_a_generated_column_is_a_column_the_settings_may_name(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "g.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V INTEGER, D INTEGER GENERATED ALWAYS AS (V * 2));",
        "INSERT INTO T (K, V) VALUES (1, 21);",
    )
    out = tmp_path / "g.tessera"
    build(db, out, Settings(tables={"T": Table(props=("D", "V"))}))
    assert _rows(out, "SELECT props FROM node") == [('{"D":42,"V":21}',)]
    assert _violations(out) == []


@pytest.mark.parametrize(
    ("label", "word"),
    [
        ('He said "hi', "said"),
        ("AND OR NOT ( ) *", "AND"),
        ("NEAR(a b", "NEAR"),
        ("col:val", "val"),
        ("a' OR 1=1 --", "OR"),
        ("caf\u00e9 \U0001f600 end", "end"),
    ],
)
def test_a_label_holding_search_syntax_is_indexed_as_text(
    tmp_path: Path, label: str, word: str
) -> None:
    # Section 3.2: the search index holds the label; it is data, not a query.
    db = tmp_path / "fts.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE T (K INTEGER PRIMARY KEY, L TEXT)")
    con.execute("INSERT INTO T VALUES (1, ?)", (label,))
    con.commit()
    con.close()
    out = tmp_path / "fts.tessera"
    build(db, out, Settings(tables={"T": Table(label="L")}))
    assert _rows(out, "SELECT label FROM node") == [(label,)]
    assert _rows(out, f"SELECT rowid FROM search WHERE search MATCH '\"{word}\"'") == [(1,)]
    assert _violations(out) == []


def test_a_node_without_label_or_summary_still_has_a_search_row(tmp_path: Path) -> None:
    # Section 3.2: one search row per node, rowid = nid; a column with nothing to hold is NULL.
    db = _database(
        tmp_path / "ns.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, L TEXT);",
        "INSERT INTO T VALUES (1, 'one'), (2, NULL), (3, 'three');",
    )
    out = tmp_path / "ns.tessera"
    build(db, out, Settings(tables={"T": Table(label="L")}))
    assert _rows(out, "SELECT rowid FROM search ORDER BY rowid") == [(1,), (2,), (3,)]
    assert _rows(out, "SELECT rowid FROM search WHERE search MATCH 'three'") == [(3,)]
    assert _violations(out) == []


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        ("1, 2, 3", "integer"),
        ("1, 2.5", "number"),
        ("1, 'a'", "json"),
        ("2.5, 'a'", "json"),
        ("NULL, NULL", "text"),
    ],
)
def test_a_column_declares_the_kind_its_values_have(tmp_path: Path, values: str, kind: str) -> None:
    # Section 3.4: declared properties map a name to a kind; values SHOULD match.
    rows = ", ".join(f"({i}, {v})" for i, v in enumerate(values.split(", "), start=1))
    db = _database(
        tmp_path / "kind.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V);",
        f"INSERT INTO T VALUES {rows};",
    )
    out = tmp_path / "kind.tessera"
    build(db, out, Settings(tables={"T": Table(props=("V",))}))
    ((declared,),) = _rows(out, "SELECT props FROM type WHERE kind = 'node'")
    assert json.loads(str(declared)) == {"V": kind}
    assert _violations(out) == []


# --- settings as recorded (section 3.3, 3.1) -----------------------------------------------


def test_header_settings_are_canonical_json_with_keys_in_utf16_order(tmp_path: Path) -> None:
    # Section 3.1: object keys sorted by UTF-16 code units; U+1F600 (D83D DE00) < U+E000.
    db = _database(
        tmp_path / "ord.db",
        'CREATE TABLE "" (K INTEGER PRIMARY KEY);'
        'CREATE TABLE "\U0001f600" (K INTEGER PRIMARY KEY);',
    )
    out = tmp_path / "ord.tessera"
    settings = Settings(tables={"": Table(type="A"), "\U0001f600": Table(type="B")})
    build(db, out, settings)
    ((text,),) = _rows(out, "SELECT settings FROM header")
    parsed = json.loads(str(text))
    names = list(parsed["tables"])
    assert names == sorted(names, key=lambda s: s.encode("utf-16-be"))
    assert names == ["\U0001f600", ""]
    assert text == settings.as_json()
    assert _violations(out) == []


# --- the source is never touched (principle 8) ---------------------------------------------


def test_the_output_path_being_the_source_is_refused_and_the_source_is_untouched(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "same.db", "CREATE TABLE T (K INTEGER PRIMARY KEY);", "INSERT INTO T VALUES (1);"
    )
    before = db.read_bytes()
    with pytest.raises((ValueError, OSError)):
        build(db, db, Settings(tables={"T": Table()}))
    assert db.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["same.db"]


def test_the_output_path_being_another_spelling_of_the_source_is_refused(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "same.db", "CREATE TABLE T (K INTEGER PRIMARY KEY);", "INSERT INTO T VALUES (1);"
    )
    before = db.read_bytes()
    link = tmp_path / "link.tessera"
    link.symlink_to(db)
    with pytest.raises((ValueError, OSError)):
        build(db, link, Settings(tables={"T": Table()}))
    assert db.read_bytes() == before
    with pytest.raises((ValueError, OSError)):
        build(db, tmp_path / "." / "same.db", Settings(tables={"T": Table()}))
    assert db.read_bytes() == before


def test_the_source_keeps_its_modification_time_and_mode(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "m.db", "CREATE TABLE T (K INTEGER PRIMARY KEY);", "INSERT INTO T VALUES (1);"
    )
    os.chmod(db, 0o444)
    os.utime(db, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    before = db.stat()
    build(db, tmp_path / "m.tessera", Settings(tables={"T": Table()}))
    after = db.stat()
    assert (after.st_mtime_ns, after.st_mode, after.st_size) == (
        before.st_mtime_ns,
        before.st_mode,
        before.st_size,
    )


def test_a_failed_build_leaves_nothing_beside_the_source_or_the_output(tmp_path: Path) -> None:
    # A late failure (second row) must not leave a partial output or temporary file.
    folder = tmp_path / "work"
    folder.mkdir()
    db = _database(
        folder / "late.db",
        PARENT + "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId INTEGER REFERENCES P);",
        "INSERT INTO C VALUES (1, 1), (2, 99);",
    )
    with pytest.raises(ValueError, match=r"late\.db"):
        build(
            db,
            folder / "late.tessera",
            Settings(tables={"P": Table(), "C": Table(foreign_keys={"PId": "in_p"})}),
        )
    assert sorted(p.name for p in folder.iterdir()) == ["late.db"]


def test_a_symlink_to_the_database_is_read_under_the_link_s_name(tmp_path: Path) -> None:
    real = _database(
        tmp_path / "real.db", "CREATE TABLE T (K INTEGER PRIMARY KEY);", "INSERT INTO T VALUES (1);"
    )
    link = tmp_path / "link.db"
    link.symlink_to(real)
    out = tmp_path / "link.tessera"
    build(link, out, Settings(tables={"T": Table()}))
    assert _rows(out, "SELECT count(*) FROM node") == [(1,)]
    assert _violations(out) == []
    assert not real.is_symlink() and real.exists()


@pytest.mark.parametrize("pragma", ["PRAGMA application_id = 1234", "PRAGMA user_version = 7"])
def test_a_database_with_its_own_application_id_or_user_version_is_read(
    tmp_path: Path, pragma: str
) -> None:
    # Section 3.1 gives application_id its meaning in a tessera/mosaic only; other values are
    # another application's and are no reason to refuse a source.
    db = _database(
        tmp_path / "app.db",
        f"{pragma};CREATE TABLE T (K INTEGER PRIMARY KEY);",
        "INSERT INTO T VALUES (1);",
    )
    out = tmp_path / "app.tessera"
    build(db, out, Settings(tables={"T": Table()}))
    assert _rows(out, "SELECT count(*) FROM node") == [(1,)]
    assert _violations(out) == []


# --- determinism across processes (principle 5, section 4.3) -------------------------------


def test_the_knowledge_hash_does_not_depend_on_the_hash_seed(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "seed.db",
        "CREATE TABLE P (Id TEXT PRIMARY KEY, N TEXT, W REAL);"
        "CREATE TABLE C (Id INTEGER PRIMARY KEY, A TEXT REFERENCES P, B TEXT REFERENCES P,"
        " V INTEGER, S TEXT);",
        "INSERT INTO P VALUES ('x', 'n1', 1.5), ('y', NULL, 2), ('z', 'é', 0.1), ('é', 'q', 3);"
        "INSERT INTO C VALUES (1, 'x', 'y', 1, 'a'), (2, 'z', 'é', 2, NULL),"
        " (3, 'y', 'y', 3, 'c');",
    )
    script = tmp_path / "run.py"  # outside the data directory
    script.write_text(
        textwrap.dedent(
            """
            import sys
            from mosaic_build.tessera.sqlite import Settings, Table, build
            s = Settings(tables={
                "P": Table(label="N", props=("N", "W")),
                "C": Table(props=("V", "S"), foreign_keys={"A": "from_a", "B": "from_b"}),
            })
            print(build(sys.argv[1], sys.argv[2], s).knowledge_hash)
            """
        )
    )
    hashes = set()
    for seed in ("0", "1", "12345", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(
            [sys.executable, str(script), str(db), str(tmp_path / f"o{seed}.tessera")],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        hashes.add(done.stdout.strip())
    assert len(hashes) == 1, hashes
    assert len(next(iter(hashes))) > 8
