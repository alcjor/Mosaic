"""``mosaic_format.create`` makes a new empty file per Spec 0.1 section 3.1.

- a single SQLite 3 database file with no journal or write-ahead log beside it;
- ``application_id`` 0x4D4F5341 and ``user_version`` 1;
- page size 4096;
- exactly the tables, indexes, virtual tables and views of ``format.sql``.
"""

import os
import sqlite3
from pathlib import Path

import mosaic_format.file
import pytest
from mosaic_format import APPLICATION_ID, KINDS, USER_VERSION, create

from tests.conftest import SPEC

SQLITE_MAGIC = b"SQLite format 3\x00"


def _objects(con: sqlite3.Connection) -> list[tuple[str, str, str, str | None]]:
    return con.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
    ).fetchall()


def _reference_objects() -> list[tuple[str, str, str, str | None]]:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript((SPEC / "format.sql").read_text(encoding="utf-8"))
        return _objects(con)
    finally:
        con.close()


@pytest.fixture
def tessera(tmp_path: Path) -> Path:
    path = tmp_path / "piece.tessera"
    returned = create(path, "tessera")
    assert returned == path
    return path


def _open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def test_tessera_is_one_sqlite_file_with_no_sidecar(tessera: Path) -> None:
    assert [p.name for p in tessera.parent.iterdir()] == [tessera.name]
    with tessera.open("rb") as f:
        assert f.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC
    for suffix in ("-journal", "-wal", "-shm"):
        assert not tessera.with_name(tessera.name + suffix).exists()


def test_tessera_pragmas_and_page_size(tessera: Path) -> None:
    con = _open_read_only(tessera)
    try:
        assert con.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert con.execute("PRAGMA user_version").fetchone()[0] == USER_VERSION
        assert con.execute("PRAGMA page_size").fetchone()[0] == 4096
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()
    # The header bytes agree: page size at offset 16, user_version at 60,
    # application_id at 68 (big-endian), file-format write/read versions 1 = rollback journal.
    raw = tessera.read_bytes()[:100]
    assert int.from_bytes(raw[16:18], "big") == 4096
    assert int.from_bytes(raw[60:64], "big") == USER_VERSION
    assert int.from_bytes(raw[68:72], "big") == APPLICATION_ID
    assert raw[18:20] == b"\x01\x01"


def test_tessera_holds_exactly_the_objects_of_format_sql(tessera: Path) -> None:
    con = _open_read_only(tessera)
    try:
        objects = _objects(con)
    finally:
        con.close()
    assert objects == _reference_objects()
    names = {(kind, name) for kind, name, _, _ in objects}
    assert ("table", "header") in names and ("view", "v_evidence") in names
    assert ("table", "search") in names and ("index", "edge_in") in names


def test_tessera_is_empty(tessera: Path) -> None:
    con = _open_read_only(tessera)
    try:
        tables = [
            name
            for (name,) in con.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'search_%'"
            )
        ]
        assert tables
        for name in tables:
            assert con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] == 0, name
    finally:
        con.close()


@pytest.mark.parametrize("kind", KINDS)
def test_both_profiles_share_the_schema(tmp_path: Path, kind: str) -> None:
    path = create(tmp_path / f"new.{kind}", kind)
    con = _open_read_only(path)
    try:
        assert _objects(con) == _reference_objects()
    finally:
        con.close()
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_created_file_accepts_rows_with_foreign_keys(tessera: Path) -> None:
    con = sqlite3.connect(tessera, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("INSERT INTO type (name, kind) VALUES ('Row', 'node')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO node VALUES (1, 'Thing:1', 'Thing', '1', NULL, NULL, NULL)")
    finally:
        con.close()


def test_unknown_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'atlas'"):
        create(tmp_path / "x.mosaic", "atlas")
    assert list(tmp_path.iterdir()) == []


def test_existing_file_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "taken.tessera"
    path.write_bytes(b"not mine")
    with pytest.raises(FileExistsError, match=r"taken\.tessera"):
        create(path, "tessera")
    assert path.read_bytes() == b"not mine"


def test_accepts_a_string_path(tmp_path: Path) -> None:
    path = create(str(tmp_path / "s.mosaic"), "mosaic")
    assert path == tmp_path / "s.mosaic" and path.is_file()


def test_dangling_symbolic_link_is_refused(tmp_path: Path) -> None:
    link = tmp_path / "link.tessera"
    elsewhere = tmp_path / "elsewhere.tessera"
    try:
        os.symlink(elsewhere, link)
    except OSError as e:  # symbolic links need a privilege on some systems
        pytest.skip(f"cannot create a symbolic link here: {e}")
    with pytest.raises(FileExistsError, match=r"link\.tessera"):
        create(link, "tessera")
    assert link.is_symlink() and not elsewhere.exists()


def test_failed_create_removes_only_its_own_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    neighbour = tmp_path / "neighbour.tessera"
    neighbour.write_bytes(b"not mine")
    monkeypatch.setattr(mosaic_format.file, "format_sql", lambda: "CREATE TABLE (;")
    with pytest.raises(sqlite3.OperationalError):
        create(tmp_path / "broken.tessera", "tessera")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["neighbour.tessera"]
    assert neighbour.read_bytes() == b"not mine"
