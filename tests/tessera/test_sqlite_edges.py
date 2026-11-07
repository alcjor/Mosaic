"""Edge cases of the SQLite tessera builder (plan M3.1; Specification 0.1 sections 3.1, 3.4, 3.5,
4.1 and 4.3), written from the spec's words and the builder's documented interface.
"""

import json
import shutil
import sqlite3
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build.tessera.sqlite import Settings, Table, build, read
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


# --- tables and keys that look odd (sections 3.4, 4.1) -------------------------------------


def test_an_empty_table_declares_its_type_and_gives_no_node(tmp_path: Path) -> None:
    # Section 3.4: every type used is declared; an empty table is still a table the settings name.
    db = _database(tmp_path / "e.db", "CREATE TABLE T (K INTEGER PRIMARY KEY, V TEXT);")
    out = tmp_path / "e.tessera"
    build(db, out, Settings(tables={"T": Table(props=("V",))}))
    assert _rows(out, "SELECT count(*) FROM node") == [(0,)]
    assert _rows(out, "SELECT count(*) FROM evidence") == [(0,)]
    assert _rows(out, "SELECT name FROM type") == [("T",)]
    assert _violations(out) == []


def test_keys_zero_negative_unicode_and_punctuation_are_kept_as_text(tmp_path: Path) -> None:
    # Section 3.4: the id is <type>:<source key>; a ':' or '=' in the key is not special.
    db = _database(
        tmp_path / "k.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY);",
        "INSERT INTO T VALUES ('0'), ('-1'), ('a:b'), ('x=y'), ('A'), ('a'), (' pad '),"
        " ('é'), (char(101, 769)), (char(128512));",
    )
    out = tmp_path / "k.tessera"
    build(db, out, Settings(tables={"T": Table()}))
    keys = {k for (k,) in _rows(out, "SELECT key FROM node")}
    assert keys == {"0", "-1", "a:b", "x=y", "A", "a", " pad ", "é", "é", "\U0001f600"}
    ids = {i for (i,) in _rows(out, "SELECT id FROM node")}
    assert ids == {f"T:{k}" for k in keys}
    locators = {loc for (loc,) in _rows(out, "SELECT locator FROM evidence")}
    assert "file=k.db;table=T;row=x=y" in locators
    assert "file=k.db;table=T;row=\U0001f600" in locators
    assert _violations(out) == []  # includes canonical order by UTF-8 bytes (section 3.6)


def test_an_integer_key_negative_or_zero_is_decimal_text(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "i.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY);",
        "INSERT INTO T VALUES (0), (-5), (9007199254740993);",
    )
    out = tmp_path / "i.tessera"
    build(db, out, Settings(tables={"T": Table()}))
    assert {k for (k,) in _rows(out, "SELECT key FROM node")} == {"0", "-5", "9007199254740993"}
    assert _violations(out) == []


def test_a_table_name_needing_quotes_works_with_an_explicit_type(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "q.db",
        'CREATE TABLE "Order Details" ("Line No" INTEGER PRIMARY KEY, "Unit ""Price""" REAL);',
        'INSERT INTO "Order Details" VALUES (1, 2.5);',
    )
    out = tmp_path / "q.tessera"
    build(
        db, out, Settings(tables={"Order Details": Table(type="Detail", props=('Unit "Price"',))})
    )
    assert _rows(out, "SELECT id, props FROM node") == [("Detail:1", '{"Unit \\"Price\\"":2.5}')]
    assert _rows(out, "SELECT locator FROM evidence") == [("file=q.db;table=Order Details;row=1",)]
    assert _violations(out) == []


def test_a_table_without_rowid_is_read(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "w.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY, V INTEGER) WITHOUT ROWID;",
        "INSERT INTO T VALUES ('b', 2), ('a', 1);",
    )
    out = tmp_path / "w.tessera"
    build(db, out, Settings(tables={"T": Table(props=("V",))}))
    assert sorted(_rows(out, "SELECT key, props FROM node")) == [("a", '{"V":1}'), ("b", '{"V":2}')]


def test_the_key_column_may_also_be_a_prop(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "p.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V TEXT);",
        "INSERT INTO T VALUES (7, 'x');",
    )
    out = tmp_path / "p.tessera"
    build(db, out, Settings(tables={"T": Table(props=("K", "V"))}))
    assert _rows(out, "SELECT props FROM node") == [('{"K":7,"V":"x"}',)]
    assert _violations(out) == []


def test_a_real_primary_key_is_its_canonical_json_text(tmp_path: Path) -> None:
    # Section 3.1: numbers are written as ECMAScript writes them.
    db = _database(
        tmp_path / "r.db",
        "CREATE TABLE T (K REAL PRIMARY KEY);",
        "INSERT INTO T VALUES (1.5), (2.0);",
    )
    out = tmp_path / "r.tessera"
    build(db, out, Settings(tables={"T": Table()}))
    assert {k for (k,) in _rows(out, "SELECT key FROM node")} == {"1.5", "2"}


# --- labels and summaries (section 3.2: the search index holds them) -----------------------


def test_a_summary_column_fills_the_summary_and_the_search_index(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "s.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, L TEXT, S TEXT);",
        "INSERT INTO T VALUES (1, 'Name one', 'a long summary'), (2, 'Name two', NULL);",
    )
    out = tmp_path / "s.tessera"
    build(db, out, Settings(tables={"T": Table(label="L", summary="S")}))
    assert _rows(out, "SELECT key, label, summary FROM node ORDER BY nid") == [
        ("1", "Name one", "a long summary"),
        ("2", "Name two", None),
    ]
    assert _rows(out, "SELECT rowid FROM search WHERE search MATCH 'summary'") == [(1,)]
    assert _violations(out) == []


def test_a_label_keeps_its_unicode_bytes_without_normalising(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "u.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, L TEXT);",
        "INSERT INTO T VALUES (1, char(233)), (2, char(101, 769)), (3, char(128512));",
    )
    out = tmp_path / "u.tessera"
    build(db, out, Settings(tables={"T": Table(label="L")}))
    labels = [lab for (lab,) in _rows(out, "SELECT label FROM node ORDER BY nid")]
    assert labels[0] == "é"
    assert labels[1] == "é"


def test_an_empty_or_numeric_label_still_gives_a_valid_tessera(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "l.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, L);",
        "INSERT INTO T VALUES (1, ''), (2, 42), (3, 1.5), (4, NULL);",
    )
    out = tmp_path / "l.tessera"
    build(db, out, Settings(tables={"T": Table(label="L")}))
    assert _violations(out) == []


@pytest.mark.parametrize("where", ["label", "summary", "key"])
def test_u0000_in_a_label_summary_or_key_is_refused(tmp_path: Path, where: str) -> None:
    # Section 3.1: text values MUST NOT contain U+0000.
    key = "'a' || char(0) || 'b'" if where == "key" else "'k'"
    val = "'a' || char(0) || 'b'"
    db = _database(
        tmp_path / "n.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY, L TEXT, S TEXT);",
        f"INSERT INTO T VALUES ({key}, {val if where == 'label' else 'NULL'},"
        f" {val if where == 'summary' else 'NULL'});",
    )
    _refused(tmp_path, db, Settings(tables={"T": Table(label="L", summary="S")}), r"n\.db")


# --- values (sections 3.1, 3.4) ------------------------------------------------------------


def test_numbers_at_the_edge_of_the_exact_integer_range(tmp_path: Path) -> None:
    # Section 3.1: an integer outside +/-(2^53 - 1) is stored as a string.
    db = _database(
        tmp_path / "n.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V INTEGER);",
        "INSERT INTO T VALUES (1, 9007199254740991), (2, 9007199254740992),"
        " (3, -9007199254740991), (4, -9007199254740992), (5, 9223372036854775807);",
    )
    out = tmp_path / "n.tessera"
    build(db, out, Settings(tables={"T": Table(props=("V",))}))
    assert _rows(out, "SELECT props FROM node ORDER BY nid") == [
        ('{"V":9007199254740991}',),
        ('{"V":"9007199254740992"}',),
        ('{"V":-9007199254740991}',),
        ('{"V":"-9007199254740992"}',),
        ('{"V":"9223372036854775807"}',),
    ]
    assert _violations(out) == []


def test_reals_are_written_as_ecmascript_writes_them(tmp_path: Path) -> None:
    # Section 3.1: RFC 8785 numbers.
    db = _database(
        tmp_path / "f.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V REAL);",
        "INSERT INTO T VALUES (1, 1e21), (2, -0.0), (3, 1e-7), (4, 100.0), (5, 0.1), (6, 5e-324);",
    )
    out = tmp_path / "f.tessera"
    build(db, out, Settings(tables={"T": Table(props=("V",))}))
    values = [json.loads(str(p))["V"] for (p,) in _rows(out, "SELECT props FROM node ORDER BY nid")]
    texts = [p for (p,) in _rows(out, "SELECT props FROM node ORDER BY nid")]
    assert texts == [
        '{"V":1e+21}',
        '{"V":0}',
        '{"V":1e-7}',
        '{"V":100}',
        '{"V":0.1}',
        '{"V":5e-324}',
    ]
    assert values[0] == 1e21
    assert _violations(out) == []


def test_a_real_with_an_integer_value_beyond_the_exact_range_is_not_written_broken(
    tmp_path: Path,
) -> None:
    # Section 3.1 says an *integer* outside +/-(2^53 - 1) is a string; a REAL such as 1.2e20 is a
    # finite double whose RFC 8785 text is plain digits. The spec does not say which it is, so
    # either a valid tessera or a refusal naming the row is accepted, never a broken file.
    db = _database(
        tmp_path / "big.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V REAL);",
        "INSERT INTO T VALUES (1, 123456789012345680000.0);",
    )
    out = tmp_path / "big.tessera"
    try:
        build(db, out, Settings(tables={"T": Table(props=("V",))}))
    except ValueError as e:
        assert "'V'" in str(e) or "1" in str(e)
        assert not out.exists()
        return
    assert _violations(out) == []


@pytest.mark.parametrize("literal", ["9e999", "-9e999"])
def test_an_infinite_real_is_refused_naming_the_row_and_column(
    tmp_path: Path, literal: str
) -> None:
    # Section 3.1 (I-JSON): no number outside the range of an IEEE 754 double.
    db = _database(
        tmp_path / "inf.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, V REAL);",
        f"INSERT INTO T VALUES (1, {literal});",
    )
    _refused(tmp_path, db, Settings(tables={"T": Table(props=("V",))}), r"row 1.*'V'")


def test_property_names_are_ordered_by_utf16_code_units_in_props(tmp_path: Path) -> None:
    # Section 3.1: object keys sorted by UTF-16 code units: U+1F600 (D83D DE00) < U+E000.
    db = _database(
        tmp_path / "o.db",
        'CREATE TABLE T (K INTEGER PRIMARY KEY, "" TEXT, "\U0001f600" TEXT, "z" TEXT);',
        "INSERT INTO T VALUES (1, 'a', 'b', 'c');",
    )
    out = tmp_path / "o.tessera"
    build(db, out, Settings(tables={"T": Table(props=("", "\U0001f600", "z"))}))
    assert _rows(out, "SELECT props FROM node") == [('{"z":"c","\U0001f600":"b","":"a"}',)]
    assert _rows(out, "SELECT props FROM type WHERE kind = 'node'") == [
        ('{"z":"text","\U0001f600":"text","":"text"}',)
    ]
    assert _violations(out) == []


@pytest.mark.parametrize("blob", ["X'ff'", "X'c328'", "X'eda080'", "X'f4908080'"])
def test_text_that_is_not_utf8_is_refused_naming_the_row(tmp_path: Path, blob: str) -> None:
    # Section 3.1 (I-JSON): no unpaired surrogates; ED A0 80 encodes one.
    db = _database(
        tmp_path / "bad.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, S TEXT);",
        f"INSERT INTO T VALUES (1, CAST({blob} AS TEXT));",
    )
    _refused(tmp_path, db, Settings(tables={"T": Table(props=("S",))}), r"bad\.db")


def test_a_long_text_value_is_kept_whole(tmp_path: Path) -> None:
    text = ("long é text " * 100_000)[:1_000_001]
    db = tmp_path / "long.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE T (K INTEGER PRIMARY KEY, S TEXT)")
    con.execute("INSERT INTO T VALUES (1, ?)", (text,))
    con.commit()
    con.close()
    out = tmp_path / "long.tessera"
    build(db, out, Settings(tables={"T": Table(props=("S",))}))
    ((props,),) = _rows(out, "SELECT props FROM node")
    assert json.loads(str(props)) == {"S": text}


def test_a_database_in_utf16_is_read_as_the_same_text(tmp_path: Path) -> None:
    schema = "CREATE TABLE T (K TEXT PRIMARY KEY, S TEXT);"
    rows = "INSERT INTO T VALUES ('é', 'café \U0001f600');"
    plain = _database(tmp_path / "plain.db", schema, rows)
    wide = tmp_path / "wide.db"
    con = sqlite3.connect(wide)
    con.execute("PRAGMA encoding = 'UTF-16le'")
    con.executescript(schema + rows)
    con.commit()
    con.close()
    settings = Settings(tables={"T": Table(props=("S",))})
    one, _ = read(plain, settings)
    two, _ = read(wide, settings)
    assert sorted(map(repr, one.nodes)) == sorted(map(repr, two.nodes))


# --- foreign keys (section 4.1) ------------------------------------------------------------

PARENT = "CREATE TABLE P (Id INTEGER PRIMARY KEY);INSERT INTO P VALUES (1), (2);"


def test_a_foreign_key_declared_at_table_level_is_an_edge(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "t.db",
        PARENT + "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId INTEGER,"
        " FOREIGN KEY (PId) REFERENCES P (Id) ON DELETE CASCADE);",
        "INSERT INTO C VALUES (9, 2);",
    )
    out = tmp_path / "t.tessera"
    build(db, out, Settings(tables={"P": Table(), "C": Table(foreign_keys={"PId": "in_p"})}))
    edges = _rows(
        out,
        "SELECT s.id, e.type, d.id FROM edge e"
        " JOIN node s ON s.nid = e.src JOIN node d ON d.nid = e.dst",
    )
    assert edges == [("C:9", "in_p", "P:2")]
    assert _violations(out) == []


def test_a_row_naming_itself_makes_a_loop_edge(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "loop.db",
        "CREATE TABLE T (Id INTEGER PRIMARY KEY, Boss INTEGER REFERENCES T (Id));",
        "INSERT INTO T VALUES (1, 1), (2, 1);",
    )
    out = tmp_path / "loop.tessera"
    build(db, out, Settings(tables={"T": Table(foreign_keys={"Boss": "reports_to"})}))
    edges = _rows(
        out,
        "SELECT s.id, d.id FROM edge e JOIN node s ON s.nid = e.src JOIN node d ON d.nid = e.dst",
    )
    assert sorted(edges) == [("T:1", "T:1"), ("T:2", "T:1")]
    assert _violations(out) == []


def test_two_columns_with_one_edge_name_to_the_same_row_keep_both_citations(
    tmp_path: Path,
) -> None:
    # Section 3.4: an edge is (src, type, dst, qualifier); both columns cite the one fact.
    db = _database(
        tmp_path / "two.db",
        PARENT + "CREATE TABLE C (Id INTEGER PRIMARY KEY,"
        " A INTEGER REFERENCES P, B INTEGER REFERENCES P);",
        "INSERT INTO C VALUES (5, 1, 1);",
    )
    out = tmp_path / "two.tessera"
    settings = Settings(
        tables={"P": Table(), "C": Table(foreign_keys={"A": "has_p", "B": "has_p"})}
    )
    try:
        build(db, out, settings)
    except ValueError:
        assert not out.exists()  # refusing is allowed; a broken file is not
        return
    assert _violations(out) == []
    fields = sorted(
        str(loc) for (loc,) in _rows(out, "SELECT locator FROM evidence WHERE eid IS NOT NULL")
    )
    assert fields == [
        "file=two.db;table=C;row=5;field=A",
        "file=two.db;table=C;row=5;field=B",
    ]


def test_one_edge_name_for_foreign_keys_to_two_tables_is_not_written_broken(
    tmp_path: Path,
) -> None:
    # Section 3.4: an edge type is declared once (from_type, to_type).
    db = _database(
        tmp_path / "mix.db",
        "CREATE TABLE P (Id INTEGER PRIMARY KEY);CREATE TABLE Q (Id INTEGER PRIMARY KEY);"
        "CREATE TABLE C (Id INTEGER PRIMARY KEY, A INTEGER REFERENCES P, B INTEGER REFERENCES Q);"
        "INSERT INTO P VALUES (1); INSERT INTO Q VALUES (1); INSERT INTO C VALUES (5, 1, 1);",
    )
    out = tmp_path / "mix.tessera"
    settings = Settings(
        tables={"P": Table(), "Q": Table(), "C": Table(foreign_keys={"A": "of", "B": "of"})}
    )
    try:
        build(db, out, settings)
    except ValueError:
        assert not out.exists()
        return
    assert _violations(out) == []


# --- evidence at scale and determinism (sections 3.5, 4.3) ---------------------------------


def test_many_rows_give_one_evidence_row_per_node_and_edge(tmp_path: Path) -> None:
    con_path = tmp_path / "big.db"
    con = sqlite3.connect(con_path)
    con.executescript(
        "CREATE TABLE P (Id INTEGER PRIMARY KEY, N TEXT);"
        "CREATE TABLE C (Id TEXT PRIMARY KEY, PId INTEGER REFERENCES P, V REAL);"
    )
    con.executemany("INSERT INTO P VALUES (?, ?)", [(i, f"p{i}") for i in range(1, 501)])
    con.executemany(
        "INSERT INTO C VALUES (?, ?, ?)", [(f"c{i:05d}", i % 500 + 1, i / 7) for i in range(3000)]
    )
    con.commit()
    con.close()
    settings = Settings(
        tables={
            "P": Table(label="N"),
            "C": Table(props=("V",), foreign_keys={"PId": "in_p"}),
        }
    )
    first = build(con_path, tmp_path / "a.tessera", settings)
    second = build(con_path, tmp_path / "b.tessera", settings)
    assert first.knowledge_hash == second.knowledge_hash
    assert _rows(first.path, "SELECT count(*) FROM node") == [(3500,)]
    assert _rows(first.path, "SELECT count(*) FROM edge") == [(3000,)]
    assert _rows(first.path, "SELECT count(*) FROM evidence") == [(6500,)]
    assert _violations(first.path) == []


def test_the_knowledge_hash_does_not_depend_on_where_the_database_lives(tmp_path: Path) -> None:
    # Section 4.3: same source and settings, same hash; the locator names the file, not its path.
    schema = "CREATE TABLE T (K INTEGER PRIMARY KEY, V TEXT);"
    rows = "INSERT INTO T VALUES (1, 'x'), (2, 'y');"
    (tmp_path / "one").mkdir()
    (tmp_path / "two" / "deeper" / "still").mkdir(parents=True)
    a = _database(tmp_path / "one" / "d.db", schema, rows)
    b = tmp_path / "two" / "deeper" / "still" / "d.db"
    shutil.copyfile(a, b)
    settings = Settings(tables={"T": Table(props=("V",))})
    assert (
        build(a, tmp_path / "a.tessera", settings).knowledge_hash
        == build(b, tmp_path / "b.tessera", settings).knowledge_hash
    )
    assert _rows(tmp_path / "b.tessera", "SELECT path FROM source") == [("d.db",)]


def test_the_order_tables_are_named_in_does_not_change_the_hash(tmp_path: Path) -> None:
    db = _database(tmp_path / "o.db", PARENT + "CREATE TABLE Q (Id INTEGER PRIMARY KEY);")
    forward = Settings(tables={"P": Table(), "Q": Table()})
    backward = Settings(tables={"Q": Table(), "P": Table()})
    a = build(db, tmp_path / "a.tessera", forward)
    b = build(db, tmp_path / "b.tessera", backward)
    assert a.knowledge_hash == b.knowledge_hash
    assert forward.as_json() == backward.as_json()


def test_a_different_setting_gives_a_different_knowledge_hash(tmp_path: Path) -> None:
    # Section 3.3: settings shape the output and are recorded; a changed type name is a change.
    db = _database(tmp_path / "d.db", "CREATE TABLE T (K INTEGER PRIMARY KEY, V TEXT);",
                   "INSERT INTO T VALUES (1, 'x');")  # fmt: skip
    a = build(db, tmp_path / "a.tessera", Settings(tables={"T": Table()}))
    b = build(db, tmp_path / "b.tessera", Settings(tables={"T": Table(type="Other")}))
    c = build(db, tmp_path / "c.tessera", Settings(tables={"T": Table(props=("V",))}))
    assert len({a.knowledge_hash, b.knowledge_hash, c.knowledge_hash}) == 3


# --- the source: path, kind, damage (principle 8; sections 4.1, 10) ------------------------


def test_a_path_with_uri_characters_is_read(tmp_path: Path) -> None:
    folder = tmp_path / "a b#c?d%20e"
    folder.mkdir()
    db = _database(
        folder / "we#ird?na%me.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY);",
        "INSERT INTO T VALUES (1);",
    )
    before = db.read_bytes()
    out = tmp_path / "uri.tessera"
    build(db, out, Settings(tables={"T": Table()}))
    assert _rows(out, "SELECT count(*) FROM node") == [(1,)]
    assert _rows(out, "SELECT path FROM source") == [("we#ird?na%me.db",)]
    assert db.read_bytes() == before
    assert sorted(p.name for p in folder.iterdir()) == ["we#ird?na%me.db"]


def test_a_missing_database_is_an_error_and_is_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    out = tmp_path / "out.tessera"
    with pytest.raises((ValueError, OSError), match=r"missing\.db"):
        build(missing, out, Settings(tables={"T": Table()}))
    assert not missing.exists()
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []


def test_an_empty_file_is_refused_naming_it_and_left_empty(tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    _refused(tmp_path, empty, Settings(tables={"T": Table()}), r"empty\.db")
    assert empty.read_bytes() == b""
    assert sorted(p.name for p in tmp_path.iterdir()) == ["empty.db"]


def test_a_directory_is_refused_naming_it(tmp_path: Path) -> None:
    folder = tmp_path / "folder.db"
    folder.mkdir()
    out = tmp_path / "out.tessera"
    with pytest.raises((ValueError, OSError), match=r"folder\.db"):
        build(folder, out, Settings(tables={"T": Table()}))
    assert not out.exists()


def test_a_truncated_database_is_refused_naming_it(tmp_path: Path) -> None:
    db = tmp_path / "cut.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE T (K INTEGER PRIMARY KEY, S TEXT)")
    con.executemany("INSERT INTO T VALUES (?, ?)", [(i, "x" * 500) for i in range(200)])
    con.commit()
    con.close()
    data = db.read_bytes()
    assert len(data) > 3 * 4096
    db.write_bytes(data[: 2 * 4096 + 100])
    _refused(tmp_path, db, Settings(tables={"T": Table(props=("S",))}), r"cut\.db")


def test_a_tessera_given_as_the_source_is_refused(tmp_path: Path) -> None:
    # Section 4.1 and ADR-003: a source MUST NOT be a tessera or a mosaic.
    base = _database(
        tmp_path / "base.db", "CREATE TABLE T (K INTEGER PRIMARY KEY);", "INSERT INTO T VALUES (1);"
    )
    made = build(base, tmp_path / "made.tessera", Settings(tables={"T": Table()}))
    source = tmp_path / "x.db"
    shutil.copyfile(made.path, source)
    _refused(
        tmp_path,
        source,
        Settings(tables={"node": Table(type="Node")}),
        r"(?i)\b(tessera|mosaic)\b",
    )
