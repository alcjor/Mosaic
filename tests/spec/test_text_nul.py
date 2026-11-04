"""Text never contains U+0000 (section 3.1, decision on #39).

These tests pin the SQLite behaviour that makes the rule necessary, and the expression a
checker can use to find a NUL in a text value.
"""

import sqlite3

import pytest

NUL_TEXT = "a\x00b"


@pytest.fixture
def con() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def test_sqlite_stores_text_after_a_nul(con: sqlite3.Connection) -> None:
    assert con.execute("SELECT hex(?)", (NUL_TEXT,)).fetchone()[0] == "610062"


def test_quote_and_length_stop_at_the_first_nul(con: sqlite3.Connection) -> None:
    """Section 3.6 hashes text as quote() writes it, so text after a NUL would go unhashed."""
    assert con.execute("SELECT quote(?), length(?)", (NUL_TEXT, NUL_TEXT)).fetchone() == ("'a'", 1)


@pytest.mark.parametrize(("text", "has_nul"), [(NUL_TEXT, True), ("ab", False), ("", False)])
def test_a_checker_finds_a_nul_by_its_bytes(
    con: sqlite3.Connection, text: str, has_nul: bool
) -> None:
    found = con.execute("SELECT instr(CAST(? AS BLOB), X'00') > 0", (text,)).fetchone()[0]
    assert bool(found) is has_nul
