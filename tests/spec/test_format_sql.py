"""format.sql loads into SQLite and its constraints carry the invariants they claim.

Spec 0.1, sections 3.1 to 3.10; Part 2, Physical model ("Constraints carry invariants").
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from mosaic_format import APPLICATION_ID, USER_VERSION

from tests.conftest import SPEC

H = "a" * 64

EXPECTED_TABLES = {
    "header",
    "source",
    "type",
    "node",
    "edge",
    "alias",
    "evidence",
    "snippet",
    "mention",
    "link_count",
    "vector",
    "search",
    "source_text",
    "external_ref",
}
EXPECTED_VIEWS = {"v_node", "v_edge", "v_alias", "v_evidence"}


def _create(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None)
    con.executescript((SPEC / "format.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    return con


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    con = _create(tmp_path / "t.mosaic")
    yield con
    con.close()


def _tessera(con: sqlite3.Connection) -> None:
    con.execute(
        "INSERT INTO header (one, format_version, kind, producer, knowledge_hash) "
        "VALUES (1, '0.1', 'tessera', 'test/0', ?)",
        (H,),
    )
    con.execute("INSERT INTO source VALUES (1, 'sheet', 'file', 'sheet.csv', ?, NULL)", (H,))
    con.execute(
        "INSERT INTO type (name, kind, props) VALUES ('Row', 'node', '{\"Tag\": \"text\"}')"
    )
    con.execute(
        "INSERT INTO type (name, kind, from_type, to_type) VALUES ('next', 'edge', 'Row', 'Row')"
    )
    con.execute("INSERT INTO node VALUES (1, 'Row:1', 'Row', '1', 'one', NULL, '{\"Tag\": \"A\"}')")
    con.execute("INSERT INTO node VALUES (2, 'Row:2', 'Row', '2', 'two', NULL, NULL)")
    con.execute("INSERT INTO edge VALUES (1, 'next', 1, 2, '', NULL)")


def test_fts5_is_available() -> None:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")


def test_schema_objects_and_pragmas(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
    assert db.execute("PRAGMA user_version").fetchone()[0] == USER_VERSION
    assert db.execute("PRAGMA page_size").fetchone()[0] == 4096
    rows = db.execute("SELECT type, name FROM sqlite_schema").fetchall()
    tables = {n for t, n in rows if t == "table" and not n.startswith(("sqlite_", "search_"))}
    views = {n for t, n in rows if t == "view"}
    assert tables == EXPECTED_TABLES
    assert views == EXPECTED_VIEWS


def test_valid_tessera_rows_insert(db: sqlite3.Connection) -> None:
    _tessera(db)
    db.execute(
        "INSERT INTO evidence (evid, nid, sid, locator, method, producer) "
        "VALUES (1, 1, 1, 'file=sheet.csv;row=2', 'extracted', 'test/0')"
    )
    db.execute(
        "INSERT INTO evidence (evid, eid, sid, locator, method, producer, confidence) "
        "VALUES (2, 1, 1, 'row=3', 'inferred', 'test/0', 0.5)"
    )
    db.execute(
        "INSERT INTO mention VALUES (1, 'TEMP_3', 'row=2;field=Tag', 1, 'csv.tag', 'identifier')"
    )
    db.execute("INSERT INTO search (rowid, label) VALUES (1, 'TEMP-3 inlet')")
    hits = db.execute("SELECT rowid FROM search WHERE search MATCH '\"TEMP-3\"'").fetchall()
    assert hits == [(1,)]
    edge = db.execute("SELECT type, src, dst FROM v_edge").fetchone()
    assert edge == ("next", "Row:1", "Row:2")


@pytest.mark.parametrize(
    "sql",
    [
        # second header row
        "INSERT INTO header (one, format_version, kind, producer, knowledge_hash) "
        "VALUES (2, '0.1', 'tessera', 'x/1', '" + H + "')",
        # inferred without confidence
        "INSERT INTO evidence (nid, sid, locator, method, producer) "
        "VALUES (1, 1, 'r=1', 'inferred', 'x')",
        # extracted with confidence
        "INSERT INTO evidence (nid, sid, locator, method, producer, confidence) "
        "VALUES (1, 1, 'r=1', 'extracted', 'x', 0.9)",
        # confidence above 1
        "INSERT INTO evidence (nid, sid, locator, method, producer, confidence) "
        "VALUES (1, 1, 'r=1', 'inferred', 'x', 1.5)",
        # two subjects
        "INSERT INTO evidence (nid, eid, sid, locator, method, producer) "
        "VALUES (1, 1, 1, 'r=1', 'extracted', 'x')",
        # edge to a missing node
        "INSERT INTO edge (type, src, dst) VALUES ('next', 1, 99)",
        # undeclared node type
        "INSERT INTO node VALUES (9, 'Thing:9', 'Thing', '9', NULL, NULL, NULL)",
        # bad node type name
        "INSERT INTO type (name, kind) VALUES ('row', 'node')",
        # bad edge type name
        "INSERT INTO type (name, kind, from_type, to_type) VALUES ('Next', 'edge', 'Row', 'Row')",
        # props not an object
        "INSERT INTO node VALUES (9, 'Row:9', 'Row', '9', NULL, NULL, '[1]')",
        # duplicate (type, key)
        "INSERT INTO node VALUES (9, 'Row:x', 'Row', '1', NULL, NULL, NULL)",
        # short vector
        "INSERT INTO vector VALUES (1, X'00')",
        # bad hash
        "INSERT INTO source VALUES (2, 's2', 'file', NULL, 'ABC', NULL)",
        # bad external system name
        "INSERT INTO external_ref (nid, system, kind, locator, sid) "
        "VALUES (1, 'Hist', 'timeseries', '{}', 1)",
    ],
)
def test_constraints_reject(db: sqlite3.Connection, sql: str) -> None:
    _tessera(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql)


def test_header_profile_rules(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):  # a mosaic needs pattern_hash and target
        db.execute(
            "INSERT INTO header (one, format_version, kind, producer, knowledge_hash) "
            "VALUES (1, '0.1', 'mosaic', 'x/1', ?)",
            (H,),
        )
    with pytest.raises(sqlite3.IntegrityError):  # vector hash without its model
        db.execute(
            "INSERT INTO header (one, format_version, kind, producer, knowledge_hash, "
            "vector_hash, pattern_hash, target) VALUES (1, '0.1', 'mosaic', 'x/1', ?, ?, ?, 'ops')",
            (H, H, H),
        )
    db.execute(
        "INSERT INTO header (one, format_version, kind, producer, knowledge_hash, vector_hash, "
        "embed_model, pattern_hash, target) "
        "VALUES (1, '0.1', 'mosaic', 'x/1', ?, ?, 'm@h', ?, 'ops')",
        (H, H, H),
    )
