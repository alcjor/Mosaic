"""The SQLite tessera builder (plan M3.1; Specification 0.1 sections 3.4, 3.5, 4.1 and 4.3).

One SQLite database gives one tessera. Each table the settings name gives one node type, each
row one node keyed by its primary key, the columns the settings name its props, and each value
of a foreign key the settings name one edge from the row to the row it names. Every node and
edge has evidence whose locator names the file, the table and the row (section 3.5). The
database is only read (principle 8), and the same database and settings give the same knowledge
hash, with the settings recorded in ``header.settings`` (sections 3.3 and 4.3).
"""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build import __version__
from mosaic_build.tessera.convert import Boolean, Date
from mosaic_build.tessera.sqlite import Settings, Table, build, read
from mosaic_format.check import check_file

PRODUCER = f"mosaic-sqlite/{__version__}"

SCHEMA = """
CREATE TABLE Writer (
    WriterId INTEGER PRIMARY KEY,
    Name     TEXT NOT NULL,
    Born     TEXT
);
CREATE TABLE Shelf (
    Code  TEXT PRIMARY KEY,
    Floor INTEGER
);
CREATE TABLE Volume (
    VolumeId  INTEGER PRIMARY KEY,
    Title     TEXT NOT NULL,
    Pages     INTEGER,
    Weight    REAL,
    Lent      INTEGER,
    WriterId  INTEGER NOT NULL REFERENCES Writer (WriterId),
    ShelfCode TEXT REFERENCES Shelf,
    SequelOf  INTEGER REFERENCES Volume (VolumeId)
);
CREATE TABLE Unlisted (Id INTEGER PRIMARY KEY, Note TEXT);
"""

ROWS = """
INSERT INTO Writer VALUES (1, 'Ada Quill', '3 March 1901'), (2, 'Bo Lark', NULL);
INSERT INTO Shelf VALUES ('A1', 0), ('B7', 2);
INSERT INTO Volume VALUES
    (10, 'Salt Roads', 312, 0.45, 1, 1, 'A1', NULL),
    (11, 'Salt Roads Again', 280, 0.5, 0, 1, 'B7', 10),
    (12, 'Quiet Hours', NULL, NULL, NULL, 2, NULL, NULL);
INSERT INTO Unlisted VALUES (1, 'not imported');
"""

SETTINGS = Settings(
    tables={
        "Writer": Table(label="Name", props=("Name", "Born")),
        "Shelf": Table(type="Place", props=("Floor",)),
        "Volume": Table(
            label="Title",
            props=("Title", "Pages", "Weight", "Lent"),
            foreign_keys={"WriterId": "written_by", "ShelfCode": "kept_on", "SequelOf": "follows"},
        ),
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
def db(tmp_path: Path) -> Path:
    return _database(tmp_path / "library.db")


@pytest.fixture
def built(db: Path) -> Path:
    out = db.with_name("library.tessera")
    build(db, out, SETTINGS)
    return out


# --- nodes, keys and props (sections 3.4, 4.1) ---------------------------------------------


def test_each_row_of_each_named_table_is_one_node_keyed_by_its_primary_key(built: Path) -> None:
    nodes = _rows(built, "SELECT id, type, key, label, summary, props FROM node ORDER BY nid")
    assert nodes == [
        ("Place:A1", "Place", "A1", None, None, '{"Floor":0}'),
        ("Place:B7", "Place", "B7", None, None, '{"Floor":2}'),
        ("Volume:10", "Volume", "10", "Salt Roads", None,
         '{"Lent":1,"Pages":312,"Title":"Salt Roads","Weight":0.45}'),
        ("Volume:11", "Volume", "11", "Salt Roads Again", None,
         '{"Lent":0,"Pages":280,"Title":"Salt Roads Again","Weight":0.5}'),
        ("Volume:12", "Volume", "12", "Quiet Hours", None, '{"Title":"Quiet Hours"}'),
        ("Writer:1", "Writer", "1", "Ada Quill", None,
         '{"Born":"3 March 1901","Name":"Ada Quill"}'),
        ("Writer:2", "Writer", "2", "Bo Lark", None, '{"Name":"Bo Lark"}'),
    ]  # fmt: skip


def test_a_table_the_settings_do_not_name_gives_nothing(built: Path) -> None:
    assert _rows(built, "SELECT count(*) FROM node WHERE type = 'Unlisted'") == [(0,)]
    assert _rows(built, "SELECT count(*) FROM type WHERE name = 'Unlisted'") == [(0,)]


def test_each_table_is_one_node_type_keyed_by_its_primary_key_column(built: Path) -> None:
    types = _rows(
        built,
        "SELECT name, kind, key_prop, from_type, to_type, props FROM type"
        " WHERE kind = 'node' ORDER BY name",
    )
    assert types == [
        ("Place", "node", "Code", None, None, '{"Floor":"integer"}'),
        ("Volume", "node", "VolumeId", None, None,
         '{"Lent":"integer","Pages":"integer","Title":"text","Weight":"number"}'),
        ("Writer", "node", "WriterId", None, None, '{"Born":"text","Name":"text"}'),
    ]  # fmt: skip


def test_values_keep_their_kind_and_null_makes_no_prop(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "values.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY, I INTEGER, R REAL, S TEXT, Big INTEGER, M);",
        "INSERT INTO T VALUES ('a', -3, 1.5, 'x y', 9007199254740993, 'text'),"
        " ('b', NULL, 2.0, '', NULL, 4);",
    )
    out = tmp_path / "values.tessera"
    build(db, out, Settings(tables={"T": Table(props=("I", "R", "S", "Big", "M"))}))
    assert _rows(out, "SELECT key, props FROM node ORDER BY nid") == [
        # An integer beyond +/-(2**53 - 1) is stored as a string (section 3.1).
        ("a", '{"Big":"9007199254740993","I":-3,"M":"text","R":1.5,"S":"x y"}'),
        ("b", '{"M":4,"R":2,"S":""}'),
    ]
    # A column holding text and numbers is declared json: its values keep their kinds.
    assert _rows(out, "SELECT props FROM type WHERE name = 'T'") == [
        ('{"Big":"integer","I":"integer","M":"json","R":"number","S":"text"}',)
    ]


def test_conversions_apply_to_a_columns_values(tmp_path: Path, db: Path) -> None:
    settings = Settings(
        tables={
            "Writer": Table(
                label="Name",
                props=("Name", "Born"),
                convert={"Born": Date(("%d %B %Y",))},
            ),
            "Volume": Table(
                props=("Lent",),
                convert={"Lent": Boolean(true=("1",), false=("0",))},
            ),
        }
    )
    out = tmp_path / "converted.tessera"
    made = build(db, out, settings)
    props = _rows(out, "SELECT id, props FROM node ORDER BY nid")
    assert props == [
        ("Volume:10", '{"Lent":true}'),
        ("Volume:11", '{"Lent":false}'),
        ("Volume:12", None),
        ("Writer:1", '{"Born":"1901-03-03","Name":"Ada Quill"}'),
        ("Writer:2", '{"Name":"Bo Lark"}'),
    ]
    kinds = _rows(out, "SELECT name, props FROM type WHERE kind = 'node' ORDER BY name")
    assert kinds == [("Volume", '{"Lent":"boolean"}'), ("Writer", '{"Born":"text","Name":"text"}')]
    assert made.report.counts() == {"Volume.Lent": 0, "Writer.Born": 0}


def test_a_value_a_conversion_cannot_read_is_kept_and_reported(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "odd.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, D TEXT);",
        "INSERT INTO T VALUES (1, '2 May 2020'), (2, 'soon'), (3, 'later');",
    )
    settings = Settings(tables={"T": Table(props=("D",), convert={"D": Date(("%d %B %Y",))})})
    made = build(db, tmp_path / "odd.tessera", settings)
    assert _rows(made.path, "SELECT props FROM node ORDER BY nid") == [
        ('{"D":"2020-05-02"}',),
        ('{"D":"soon"}',),
        ('{"D":"later"}',),
    ]
    assert made.report.unconverted == {"T.D": ("2", "3")}  # by key


# --- foreign keys (sections 3.4, 4.1) ------------------------------------------------------


def test_each_foreign_key_value_is_one_edge_to_the_row_it_names(built: Path) -> None:
    edges = _rows(
        built,
        "SELECT s.id, e.type, d.id, e.qualifier, e.props FROM edge e"
        " JOIN node s ON s.nid = e.src JOIN node d ON d.nid = e.dst ORDER BY e.eid",
    )
    # A NULL foreign key makes no edge; SequelOf names a row of its own table.
    assert sorted(edges) == [
        ("Volume:10", "kept_on", "Place:A1", "", None),
        ("Volume:10", "written_by", "Writer:1", "", None),
        ("Volume:11", "follows", "Volume:10", "", None),
        ("Volume:11", "kept_on", "Place:B7", "", None),
        ("Volume:11", "written_by", "Writer:1", "", None),
        ("Volume:12", "written_by", "Writer:2", "", None),
    ]


def test_each_foreign_key_is_an_edge_type_from_its_table_to_the_table_it_names(
    built: Path,
) -> None:
    types = _rows(
        built,
        "SELECT name, key_prop, from_type, to_type, props FROM type"
        " WHERE kind = 'edge' ORDER BY name",
    )
    assert types == [
        ("follows", None, "Volume", "Volume", "{}"),
        ("kept_on", None, "Volume", "Place", "{}"),
        ("written_by", None, "Volume", "Writer", "{}"),
    ]


def test_a_foreign_key_the_settings_do_not_name_makes_no_edge(tmp_path: Path, db: Path) -> None:
    settings = Settings(
        tables={
            "Writer": Table(),
            "Volume": Table(foreign_keys={"WriterId": "written_by"}),
        }
    )
    out = tmp_path / "some.tessera"
    build(db, out, settings)
    assert _rows(out, "SELECT DISTINCT type FROM edge") == [("written_by",)]


def test_a_foreign_key_to_a_unique_column_names_that_row(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "unique.db",
        "CREATE TABLE P (Id INTEGER PRIMARY KEY, Code TEXT UNIQUE);"
        "CREATE TABLE C (Id INTEGER PRIMARY KEY, PCode TEXT REFERENCES P (Code));",
        "INSERT INTO P VALUES (1, 'x'), (2, 'y'); INSERT INTO C VALUES (5, 'y');",
    )
    out = tmp_path / "unique.tessera"
    build(db, out, Settings(tables={"P": Table(), "C": Table(foreign_keys={"PCode": "in_p"})}))
    edges = _rows(
        out,
        "SELECT s.id, e.type, d.id FROM edge e"
        " JOIN node s ON s.nid = e.src JOIN node d ON d.nid = e.dst",
    )
    assert edges == [("C:5", "in_p", "P:2")]


# --- evidence (section 3.5) ----------------------------------------------------------------


def test_every_node_has_evidence_naming_the_table_and_the_row(built: Path) -> None:
    evidence = _rows(
        built,
        "SELECT n.id, e.prop, s.id, e.locator, e.method, e.producer, e.confidence, e.via"
        " FROM evidence e JOIN node n USING (nid) JOIN source s USING (sid) ORDER BY e.evid",
    )
    assert evidence == [
        (f"{t}:{k}", None, "library.db", f"file=library.db;table={table};row={k}", "extracted",
         PRODUCER, None, None)
        for t, table, k in [
            ("Place", "Shelf", "A1"), ("Place", "Shelf", "B7"), ("Volume", "Volume", "10"),
            ("Volume", "Volume", "11"), ("Volume", "Volume", "12"), ("Writer", "Writer", "1"),
            ("Writer", "Writer", "2"),
        ]
    ]  # fmt: skip


def test_every_edge_has_evidence_naming_the_table_the_row_and_the_column(built: Path) -> None:
    evidence = _rows(
        built,
        "SELECT s.id, x.type, d.id, e.locator, e.method, e.producer FROM evidence e"
        " JOIN edge x USING (eid) JOIN node s ON s.nid = x.src JOIN node d ON d.nid = x.dst",
    )
    assert sorted(evidence) == [
        ("Volume:10", "kept_on", "Place:A1",
         "file=library.db;table=Volume;row=10;field=ShelfCode", "extracted", PRODUCER),
        ("Volume:10", "written_by", "Writer:1",
         "file=library.db;table=Volume;row=10;field=WriterId", "extracted", PRODUCER),
        ("Volume:11", "follows", "Volume:10",
         "file=library.db;table=Volume;row=11;field=SequelOf", "extracted", PRODUCER),
        ("Volume:11", "kept_on", "Place:B7",
         "file=library.db;table=Volume;row=11;field=ShelfCode", "extracted", PRODUCER),
        ("Volume:11", "written_by", "Writer:1",
         "file=library.db;table=Volume;row=11;field=WriterId", "extracted", PRODUCER),
        ("Volume:12", "written_by", "Writer:2",
         "file=library.db;table=Volume;row=12;field=WriterId", "extracted", PRODUCER),
    ]  # fmt: skip


def test_the_one_source_is_the_database_with_the_hash_of_its_bytes(built: Path, db: Path) -> None:
    sources = _rows(built, "SELECT id, kind, path, hash, notice FROM source")
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    assert sources == [("library.db", "database", "library.db", digest, None)]


def test_the_tessera_passes_check_file(built: Path) -> None:
    report = check_file(built)
    assert [str(v) for v in report.violations] == []


def test_nothing_but_the_graph_evidence_and_search_is_filled(built: Path) -> None:
    for table in ("alias", "snippet", "mention", "link_count", "vector", "source_text",
                  "external_ref"):  # fmt: skip
        assert _rows(built, f"SELECT count(*) FROM {table}") == [(0,)], table


# --- the header and determinism (sections 3.3, 4.3) ----------------------------------------


def test_the_header_is_a_tessera_recording_its_producer_and_settings(built: Path) -> None:
    (header,) = _rows(
        built,
        "SELECT format_version, kind, producer, settings, vector_hash, embed_model,"
        " pattern_hash, target, ai_model FROM header",
    )
    assert header[:3] == ("0.1", "tessera", PRODUCER)
    assert json.loads(str(header[3])) == {
        "tables": {
            "Shelf": {"type": "Place", "label": None, "summary": None, "props": ["Floor"]},
            "Volume": {
                "type": "Volume",
                "label": "Title",
                "summary": None,
                "props": ["Title", "Pages", "Weight", "Lent"],
                "foreign_keys": {
                    "WriterId": "written_by",
                    "ShelfCode": "kept_on",
                    "SequelOf": "follows",
                },
            },
            "Writer": {"type": "Writer", "label": "Name", "summary": None,
                       "props": ["Name", "Born"]},
        }
    }  # fmt: skip
    assert header[3] == SETTINGS.as_json()
    assert header[4:] == (None, None, None, None, None)


def test_the_same_database_and_settings_give_the_same_knowledge_hash(
    tmp_path: Path, db: Path
) -> None:
    first = build(db, tmp_path / "a.tessera", SETTINGS)
    second = build(db, tmp_path / "b.tessera", SETTINGS)
    assert first.knowledge_hash == second.knowledge_hash
    with mosaic_format.open(first.path) as f:
        assert f.knowledge_hash == first.knowledge_hash


def test_the_same_rows_written_in_another_order_give_the_same_graph(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    statements = [s for s in ROWS.split(";") if s.strip()]
    a = _database(tmp_path / "a" / "library.db")
    b = _database(tmp_path / "b" / "library.db", rows=";".join(reversed(statements)) + ";")
    one, _ = read(a, SETTINGS)
    two, _ = read(b, SETTINGS)
    assert sorted(map(repr, one.nodes)) == sorted(map(repr, two.nodes))
    assert sorted(map(repr, one.edges)) == sorted(map(repr, two.edges))
    assert sorted(map(repr, one.evidence)) == sorted(map(repr, two.evidence))


# --- the source is only read (principle 8) -------------------------------------------------


def test_the_database_is_byte_identical_and_untouched_after_import(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    db = _database(tmp_path / "src" / "library.db")
    before = db.read_bytes()
    stat = db.stat()
    db.chmod(0o444)
    build(db, tmp_path / "out.tessera", SETTINGS)
    assert db.read_bytes() == before
    assert db.stat().st_mtime_ns == stat.st_mtime_ns
    assert sorted(os.listdir(db.parent)) == ["library.db"]


def test_a_database_in_write_ahead_log_mode_is_read_and_left_as_it_was(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    db = tmp_path / "src" / "library.db"
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode = wal")
    con.executescript(SCHEMA + ROWS)
    con.commit()
    con.close()  # the last connection checkpoints and removes the log
    assert sorted(os.listdir(db.parent)) == ["library.db"]
    before = db.read_bytes()
    made = build(db, tmp_path / "wal.tessera", SETTINGS)
    assert db.read_bytes() == before
    assert sorted(os.listdir(db.parent)) == ["library.db"]
    assert _rows(made.path, "SELECT count(*) FROM node") == [(7,)]


@pytest.mark.parametrize("beside", ["-wal", "-journal"])
def test_a_database_with_a_log_beside_it_is_refused(tmp_path: Path, db: Path, beside: str) -> None:
    """Its content is not the file's bytes alone, so the source hash would not name it."""
    log = db.with_name(db.name + beside)
    log.write_bytes(b"pending")
    out = tmp_path / "out.tessera"
    with pytest.raises(ValueError, match=f"library.db.*{beside}"):
        build(db, out, SETTINGS)
    assert not out.exists()
    assert log.read_bytes() == b"pending"


# --- what the builder refuses --------------------------------------------------------------


def _refused(tmp_path: Path, db: Path, settings: Settings, match: str) -> None:
    out = tmp_path / "refused.tessera"
    with pytest.raises(ValueError, match=match):
        build(db, out, settings)
    assert not out.exists()


def test_a_file_that_is_not_a_database_is_refused_naming_it(tmp_path: Path) -> None:
    path = tmp_path / "notes.db"
    path.write_bytes(b"just some text, not a database\n" * 10)
    _refused(tmp_path, path, SETTINGS, r"notes\.db.*not a SQLite database")


@pytest.mark.parametrize(
    ("settings", "match"),
    [
        (Settings(tables={"Nowhere": Table()}), r"library\.db.*table 'Nowhere'"),
        (Settings(tables={"Writer": Table(props=("Age",))}), r"Writer.*column 'Age'"),
        (Settings(tables={"Writer": Table(label="Nick")}), r"Writer.*column 'Nick'"),
        (
            Settings(tables={"Writer": Table(foreign_keys={"Name": "named"})}),
            r"Writer.*'Name'.*no foreign key",
        ),
        (
            Settings(tables={"Volume": Table(foreign_keys={"WriterId": "written_by"})}),
            r"Volume.*'WriterId'.*'Writer'.*settings",
        ),
        (Settings(tables={"Writer": Table(type="writer")}), r"Writer.*type 'writer'"),
        (
            Settings(tables={"Writer": Table(type="X"), "Shelf": Table(type="X")}),
            r"type 'X'",
        ),
        (
            Settings(
                tables={
                    "Writer": Table(),
                    "Volume": Table(foreign_keys={"WriterId": "Written"}),
                }
            ),
            r"Volume.*edge 'Written'",
        ),
        (Settings(tables={}), r"no table"),
    ],
    ids=[
        "unknown-table",
        "unknown-prop",
        "unknown-label",
        "no-such-foreign-key",
        "foreign-key-to-an-unnamed-table",
        "bad-type-name",
        "type-twice",
        "bad-edge-name",
        "no-tables",
    ],
)
def test_wrong_settings_are_refused_naming_the_setting(
    tmp_path: Path, db: Path, settings: Settings, match: str
) -> None:
    _refused(tmp_path, db, settings, match)


def test_a_foreign_key_value_naming_no_row_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "dangling.db",
        "CREATE TABLE P (Id INTEGER PRIMARY KEY);"
        "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId INTEGER REFERENCES P);",
        "INSERT INTO P VALUES (1); INSERT INTO C VALUES (7, 2);",
    )
    settings = Settings(tables={"P": Table(), "C": Table(foreign_keys={"PId": "in_p"})})
    _refused(tmp_path, db, settings, r"dangling\.db: table 'C' row 7: 'PId'.*no row")


def test_a_table_without_a_primary_key_is_refused(tmp_path: Path) -> None:
    db = _database(tmp_path / "nokey.db", "CREATE TABLE T (A TEXT);", "INSERT INTO T VALUES ('x');")
    _refused(tmp_path, db, Settings(tables={"T": Table()}), r"nokey\.db: table 'T'.*primary key")


def test_a_table_whose_primary_key_has_two_columns_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "pair.db",
        "CREATE TABLE T (A INTEGER, B INTEGER, PRIMARY KEY (A, B));",
        "INSERT INTO T VALUES (1, 2);",
    )
    _refused(tmp_path, db, Settings(tables={"T": Table()}), r"pair\.db: table 'T'.*2 columns")


def test_a_null_or_empty_key_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "nullkey.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY);",
        "INSERT INTO T VALUES ('');",
    )
    _refused(tmp_path, db, Settings(tables={"T": Table()}), r"nullkey\.db: table 'T'.*empty")


def test_a_key_with_a_semicolon_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "semi.db",
        "CREATE TABLE T (K TEXT PRIMARY KEY);",
        "INSERT INTO T VALUES ('a;b');",
    )
    _refused(tmp_path, db, Settings(tables={"T": Table()}), r"semi\.db: table 'T'.*';'")


def test_a_blob_value_is_refused_naming_the_row_and_column(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "blob.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, B BLOB);",
        "INSERT INTO T VALUES (1, X'00ff');",
    )
    _refused(
        tmp_path, db, Settings(tables={"T": Table(props=("B",))}), r"table 'T' row 1: 'B'.*blob"
    )


def test_text_holding_u0000_is_refused(tmp_path: Path) -> None:
    db = _database(
        tmp_path / "nul.db",
        "CREATE TABLE T (K INTEGER PRIMARY KEY, S TEXT);",
        "INSERT INTO T VALUES (1, 'a' || char(0) || 'b');",
    )
    _refused(tmp_path, db, Settings(tables={"T": Table(props=("S",))}), r"row 1: 'S'.*U\+0000")


@pytest.mark.parametrize(
    ("schema", "match"),
    [
        (
            "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId REFERENCES P);CREATE TABLE P (A TEXT);",
            r"table 'P' has no primary key",
        ),
        (
            "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId REFERENCES P);",
            r"table 'P' is not a table",
        ),
        (
            "CREATE TABLE C (Id INTEGER PRIMARY KEY, PId REFERENCES P (Nope));"
            "CREATE TABLE P (Id INTEGER PRIMARY KEY);",
            r"table 'C': column 'PId'.*column 'Nope' of table 'P'",
        ),
    ],
    ids=["parent-without-a-key", "parent-not-a-table", "parent-column-missing"],
)
def test_a_foreign_key_whose_parent_cannot_be_read_is_refused(
    tmp_path: Path, schema: str, match: str
) -> None:
    """The child table is named first, so its foreign key is read before the parent."""
    db = _database(tmp_path / "parent.db", schema, "")
    settings = Settings(tables={"C": Table(foreign_keys={"PId": "in_p"}), "P": Table()})
    _refused(tmp_path, db, settings, match)
