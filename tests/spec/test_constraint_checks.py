"""Constraints of format.sql hold on every row, and a mosaic's `source` layout (decisions on #9).

Section 3.1: SQLite does not re-check constraints when a file is opened, so a file crafted with
`ignore_check_constraints` or with foreign keys off looks normal; `PRAGMA integrity_check` and
`PRAGMA foreign_key_check` find such rows. Section 3.2: a mosaic's `source` holds its pieces,
their original sources and `proposals.yaml`.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import SPEC

H = "a" * 64


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(tmp_path / "t.mosaic", isolation_level=None)
    con.executescript((SPEC / "format.sql").read_text(encoding="utf-8"))
    yield con
    con.close()


def _graph(con: sqlite3.Connection) -> None:
    con.execute("INSERT INTO source VALUES (1, 'sheet', 'file', 'sheet.csv', ?, NULL)", (H,))
    con.execute("INSERT INTO type (name, kind, key_prop, props) VALUES ('Row', 'node', 'k', '{}')")
    con.execute("INSERT INTO node VALUES (1, 'Row:1', 'Row', '1', 'one', NULL, NULL)")


def test_integrity_check_finds_a_row_written_past_a_check_constraint(
    db: sqlite3.Connection,
) -> None:
    _graph(db)
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    db.execute("PRAGMA ignore_check_constraints = ON")
    db.execute("INSERT INTO alias VALUES ('first', 1, 'bogus')")
    db.execute("PRAGMA ignore_check_constraints = OFF")
    problems = [r[0] for r in db.execute("PRAGMA integrity_check")]
    assert any("CHECK constraint failed in alias" in p for p in problems), problems


def test_foreign_key_check_finds_a_dangling_reference(db: sqlite3.Connection) -> None:
    _graph(db)
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute(
        "INSERT INTO evidence (evid, nid, sid, locator, method, producer) "
        "VALUES (1, 1, 99, 'row=1', 'extracted', 'test/0')"
    )
    assert ("evidence", 1, "source", 0) in db.execute("PRAGMA foreign_key_check").fetchall()


def test_a_mosaic_source_holds_pieces_original_sources_and_proposals(
    db: sqlite3.Connection,
) -> None:
    """Section 3.2 (decisions on #9 and #66).

    The pieces are the tessera and mosaic rows, and copied sources are prefixed by piece name.
    """
    rows = [
        (1, "plant", "mosaic", "b" * 64, None),
        (2, "plant/sensorlist/sensors.csv", "file", "e" * 64, None),
        (3, "proposals.yaml", "file", "c" * 64, None),
        (4, "sensorlist", "tessera", "d" * 64, None),
        (5, "sensorlist/sensors.csv", "file", "e" * 64, "CC BY 4.0"),
    ]
    db.executemany("INSERT INTO source (sid, id, kind, hash, notice) VALUES (?,?,?,?,?)", rows)
    # Decision on #66: one file through two pieces is two rows, each with its piece's notice.
    same_file = db.execute("SELECT id, notice FROM source WHERE hash = ? ORDER BY sid", ("e" * 64,))
    assert same_file.fetchall() == [
        ("plant/sensorlist/sensors.csv", None),
        ("sensorlist/sensors.csv", "CC BY 4.0"),
    ]
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_unprefixed_copies_of_one_file_would_collide(db: sqlite3.Connection) -> None:
    """Why copied ids carry their piece's name (decision on #66): `source.id` is UNIQUE, so the
    same file arriving through two pieces could not be two rows under its own id."""
    db.execute(
        "INSERT INTO source (sid, id, kind, hash) VALUES (1, 'sensors.csv', 'file', ?)", (H,)
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        db.execute(
            "INSERT INTO source (sid, id, kind, hash) VALUES (2, 'sensors.csv', 'file', ?)", (H,)
        )
