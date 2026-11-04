"""``mosaic_format.open`` opens a file by the reading rules (Spec 0.1 section 3.8).

A reader MUST:

1. open the file read-only and immutable;
2. check ``application_id``, ``user_version``, the schema (section 3.1) and the header, and
   refuse a file whose format version it does not implement, a newer minor version included
   (section 9, decided on issue #8);
3. recompute the knowledge hash and, if present, the vector hash on every open, and refuse
   the file on a mismatch;
4. treat every value as untrusted (section 10) and bound query time and result size.

Every test below starts from a file sealed by ``mosaic_format.seal`` and changes it the way a
damaged or crafted file would be changed.
"""

import hashlib
import sqlite3
import time
from pathlib import Path

import pytest
from mosaic_format import APPLICATION_ID, FORMAT_VERSION, USER_VERSION, open, seal
from mosaic_format.reader import FileRefusedError, Limits, QueryLimitError, SealedFile

from tests.format.test_writer import sample

SIDECARS = ("-journal", "-wal", "-shm")


def sealed(tmp_path: Path, kind: str = "mosaic", name: str = "file.db") -> Path:
    path = tmp_path / name
    seal(path, sample(kind))
    return path


def tamper(path: Path, *statements: str) -> None:
    """Change a sealed file in place with ordinary SQL, as anyone holding a copy could."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        for statement in statements:
            con.execute(statement)
    finally:
        con.close()
    for suffix in SIDECARS:
        assert not path.with_name(path.name + suffix).exists()


def refused(path: Path, *needles: str) -> str:
    """Open ``path``, expect a refusal, and check the message names the file and each needle."""
    with pytest.raises(FileRefusedError) as caught:
        open(path)
    message = str(caught.value)
    assert str(path) in message
    for needle in needles:
        assert needle in message, message
    return message


# --- A sealed file opens -------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["tessera", "mosaic"])
def test_a_sealed_file_opens_with_its_header(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "file.db"
    result = seal(path, sample(kind))
    with open(path) as f:
        assert isinstance(f, SealedFile)
        assert f.path == path
        assert f.kind == kind
        assert f.format_version == FORMAT_VERSION
        assert f.knowledge_hash == result.knowledge_hash
        assert f.vector_hash == result.vector_hash
        assert (f.vector_hash is None) == (kind == "tessera")
        assert f.header["producer"] == "sample/1"
        assert f.header["kind"] == kind
        assert f.query("SELECT count(*) FROM node") == [(18,)]


def test_open_accepts_sqlite_stat1(tmp_path: Path) -> None:
    """Sealing runs ANALYZE, so a sealed file carries sqlite_stat1, which section 3.1 allows."""
    path = sealed(tmp_path)
    con = sqlite3.connect(path)
    names = {n for (n,) in con.execute("SELECT name FROM sqlite_schema")}
    con.close()
    assert "sqlite_stat1" in names
    with open(path) as f:
        assert f.kind == "mosaic"


def test_open_never_writes_to_the_file(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    with open(path) as f:
        f.query("SELECT id FROM node ORDER BY nid")
        f.query("SELECT rowid FROM search WHERE search MATCH 'snipa'")
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime
    assert sorted(p.name for p in tmp_path.iterdir()) == ["file.db"]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE node SET label = 'x'",
        "DELETE FROM alias",
        "INSERT INTO type (name, kind) VALUES ('Extra', 'node')",
        "CREATE TABLE extra (x)",
        "DROP TABLE source_text",
        "PRAGMA user_version = 2",
    ],
)
def test_the_file_is_open_read_only(tmp_path: Path, statement: str) -> None:
    path = sealed(tmp_path)
    before = path.read_bytes()
    with open(path) as f, pytest.raises(sqlite3.DatabaseError):
        f.query(statement)
    assert path.read_bytes() == before


def test_a_query_cannot_attach_another_file(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    other = sealed(tmp_path, name="other.db")
    with open(path) as f, pytest.raises(sqlite3.DatabaseError):
        f.query("ATTACH DATABASE ? AS other", (str(other),))


def test_full_text_search_works_through_the_reader(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    with open(path) as f:
        hits = f.query(
            "SELECT n.id FROM search JOIN node AS n ON n.nid = search.rowid "
            "WHERE search MATCH ? ORDER BY n.id",
            ('"snipa"',),
        )
    assert ("Thing:a",) in hits
    assert ("Group:g1",) not in hits


def test_closed_file_refuses_queries(tmp_path: Path) -> None:
    f = open(sealed(tmp_path))
    f.close()
    with pytest.raises(sqlite3.ProgrammingError):
        f.query("SELECT 1")


# --- Container and schema (section 3.1) ----------------------------------------------------


def test_missing_file_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        open(path)
    assert not path.exists()


def test_a_file_that_is_not_sqlite_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "file.db"
    path.write_bytes(b"not a database, just some text that is long enough " * 100)
    refused(path, "SQLite")


@pytest.mark.parametrize("suffix", SIDECARS)
def test_a_journal_beside_the_file_is_refused(tmp_path: Path, suffix: str) -> None:
    path = sealed(tmp_path)
    path.with_name(path.name + suffix).write_bytes(b"")
    refused(path, suffix, "3.1")


def test_wrong_application_id_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "PRAGMA application_id = 1")
    refused(path, "application_id", "0x00000001", f"0x{APPLICATION_ID:08X}")


def test_wrong_user_version_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "PRAGMA user_version = 0")
    refused(path, "user_version", "0", str(USER_VERSION))


def test_extra_table_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "CREATE TABLE extra (x)")
    refused(path, "schema", "extra")


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE INDEX extra_index ON node (label)",
        "CREATE VIEW v_extra AS SELECT id FROM node",
        "CREATE TRIGGER t_extra AFTER INSERT ON node BEGIN SELECT 1; END",
    ],
)
def test_extra_object_is_refused(tmp_path: Path, statement: str) -> None:
    path = sealed(tmp_path)
    tamper(path, statement)
    refused(path, "schema", "_extra")


def test_missing_index_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "DROP INDEX edge_in")
    refused(path, "schema", "edge_in")


def test_missing_table_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "DROP TABLE external_ref")
    refused(path, "schema", "external_ref")


def test_changed_definition_is_refused(tmp_path: Path) -> None:
    """Same name, different definition: section 3.1 asks for the same definitions."""
    path = sealed(tmp_path)
    tamper(path, "DROP INDEX edge_in", "CREATE INDEX edge_in ON edge (type, dst)")
    refused(path, "schema", "edge_in")


def test_other_internal_tables_than_statistics_are_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "CREATE TABLE extra (n INTEGER PRIMARY KEY AUTOINCREMENT)", "DROP TABLE extra")
    # Dropping the only AUTOINCREMENT table leaves sqlite_sequence behind.
    con = sqlite3.connect(path)
    query = "SELECT count(*) FROM sqlite_schema WHERE name = 'sqlite_sequence'"
    assert con.execute(query).fetchone() == (1,)
    con.close()
    refused(path, "schema", "sqlite_sequence")


def test_a_header_that_is_an_endless_view_is_refused_quickly(tmp_path: Path) -> None:
    """Every file is untrusted (section 10): a crafted ``header`` must not hang the reader."""
    path = sealed(tmp_path)
    tamper(
        path,
        "DROP TABLE header",
        "CREATE VIEW header AS WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c)"
        " SELECT '0.1' AS format_version FROM c WHERE x < 0",
    )
    started = time.monotonic()
    refused(path, "schema", "header")
    assert time.monotonic() - started < 5


# --- Header and version (sections 3.3, 3.8 step 2, 9) --------------------------------------


def test_two_header_rows_are_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(
        path,
        "PRAGMA ignore_check_constraints = ON",
        "INSERT INTO header SELECT 2, format_version, kind, producer, settings, knowledge_hash,"
        " vector_hash, embed_model, pattern_hash, target, ai_model FROM header",
    )
    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM header").fetchone() == (2,)
    con.close()
    refused(path, "header", "2 rows")


def test_no_header_row_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "DELETE FROM header")
    refused(path, "header", "0 rows")


def test_unknown_kind_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "PRAGMA ignore_check_constraints = ON", "UPDATE header SET kind = 'other'")
    refused(path, "kind", "'other'")


def _newer_version(version: str, user_version: int | None, extra_table: bool) -> list[str]:
    statements = [
        "PRAGMA ignore_check_constraints = ON",
        f"UPDATE header SET format_version = '{version}'",
    ]
    if user_version is not None:
        statements.append(f"PRAGMA user_version = {user_version}")
    if extra_table:
        # What a minor version may add (section 9): an optional table.
        statements.append("CREATE TABLE added_in_newer_version (x)")
    return statements


@pytest.mark.parametrize(
    ("user_version", "extra_table"),
    [(None, False), (None, True), (2, True)],
    ids=["same-schema", "added-table", "user_version-2"],
)
def test_newer_minor_version_is_refused(
    tmp_path: Path, user_version: int | None, extra_table: bool
) -> None:
    """Section 9 as decided on #8: a newer minor version is refused, not read."""
    path = sealed(tmp_path)
    tamper(path, *_newer_version("0.2", user_version, extra_table))
    message = refused(path, "format version", "section 9")
    assert ("'0.2'" in message) or ("user_version 2" in message)
    assert "knowledge hash" not in message  # refused for its version, before any hashing


@pytest.mark.parametrize(
    ("user_version", "extra_table"),
    [(None, False), (None, True), (2, False)],
    ids=["same-schema", "added-table", "user_version-2"],
)
def test_newer_major_version_is_refused(
    tmp_path: Path, user_version: int | None, extra_table: bool
) -> None:
    path = sealed(tmp_path)
    tamper(path, *_newer_version("1.0", user_version, extra_table))
    message = refused(path, "format version", "section 9")
    assert ("'1.0'" in message) or ("user_version 2" in message)


def test_newer_minor_version_with_an_added_header_column_is_refused_for_its_version(
    tmp_path: Path,
) -> None:
    """A minor version may add a column to ``header`` (section 9): refused for its version.

    The reader reads ``format_version`` whenever ``header`` is a plain table with that column,
    so the message names the version, not a schema mismatch (#54).
    """
    path = sealed(tmp_path)
    tamper(
        path,
        *_newer_version("0.2", None, False),
        "ALTER TABLE header ADD COLUMN added_in_newer_version TEXT",
    )
    message = refused(path, "format version", "'0.2'", "section 9")
    assert "schema" not in message
    assert "knowledge hash" not in message


def test_an_added_header_column_in_version_0_1_is_a_schema_mismatch(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "ALTER TABLE header ADD COLUMN added TEXT")
    refused(path, "schema", "table header differs")


def test_a_header_whose_format_version_is_generated_is_a_schema_mismatch(
    tmp_path: Path,
) -> None:
    """Only a stored ``format_version`` is read before the schema check (section 10)."""
    path = sealed(tmp_path)
    tamper(
        path,
        "DROP TABLE header",
        "CREATE TABLE header (one INTEGER PRIMARY KEY, kind TEXT,"
        " format_version TEXT GENERATED ALWAYS AS ('9.9') VIRTUAL)",
        "INSERT INTO header (one, kind) VALUES (1, 'mosaic')",
    )
    message = refused(path, "schema", "header")
    assert "'9.9'" not in message


def test_at_most_two_rows_of_a_crafted_header_are_read_for_the_version(tmp_path: Path) -> None:
    """A crafted ``header`` may hold many rows (section 10): only two are read for the version.

    The third row's version is never read, so the file is refused by the schema check.
    """
    path = sealed(tmp_path)
    tamper(
        path,
        "DROP TABLE header",
        "CREATE TABLE header (format_version TEXT, kind TEXT)",
        "INSERT INTO header VALUES ('0.1', 'mosaic'), ('0.1', 'mosaic'), ('0.2', 'mosaic')",
    )
    message = refused(path, "schema", "header")
    assert "'0.2'" not in message


def test_a_crafted_header_with_many_rows_is_refused_quickly(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(
        path,
        "DROP TABLE header",
        "CREATE TABLE header (format_version TEXT, kind TEXT)",
        "INSERT INTO header WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c"
        " WHERE x < 200000) SELECT '0.1', 'mosaic' FROM c",
    )
    started = time.monotonic()
    refused(path, "schema", "header")
    assert time.monotonic() - started < 5


def test_older_or_malformed_version_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, *_newer_version("0.0", None, False))
    refused(path, "format version", "'0.0'")


# --- Hashes (section 3.8 step 3) -----------------------------------------------------------

TAMPERED_ROWS: dict[str, str] = {
    "node-label": "UPDATE node SET label = 'changed' WHERE nid = 1",
    "edge-props": "UPDATE edge SET props = '{\"w\":1}' WHERE eid = 1",
    "alias-removed": "DELETE FROM alias WHERE text = 'same'",
    "evidence-locator": "UPDATE evidence SET locator = 'row=999' WHERE evid = 1",
    "snippet-text": "UPDATE snippet SET text = 'other' WHERE evid = 1",
    "source-hash": f"UPDATE source SET hash = '{'c' * 64}' WHERE sid = 1",
    "header-kind-hash": f"UPDATE header SET knowledge_hash = '{'d' * 64}'",
}


@pytest.mark.parametrize("statement", TAMPERED_ROWS.values(), ids=TAMPERED_ROWS.keys())
def test_tampered_row_is_refused(tmp_path: Path, statement: str) -> None:
    path = sealed(tmp_path)
    tamper(path, statement)
    refused(path, "knowledge hash", "mismatch")


def test_tampered_row_in_a_tessera_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path, "tessera")
    tamper(path, "UPDATE mention SET text = 'other' WHERE mid = 1")
    refused(path, "knowledge hash", "mismatch")


# Values the knowledge hash cannot encode (section 3.6). `CHECK` constraints are not re-checked
# on open, so a schema-exact file written with `ignore_check_constraints` reaches the hashing;
# it must be refused like any other bad file, naming it (sections 3.8 step 3 and 10, #54).
UNENCODABLE: dict[str, tuple[str, str, str, str]] = {
    # id: (table, column, row, value as SQL), and the value's storage class is not the hashed one
    "confidence-text": ("evidence", "confidence", "evid = 1", "'high'"),
    "confidence-blob": ("evidence", "confidence", "evid = 1", "X'01'"),
    "real-in-edge-src": ("edge", "src", "eid = 1", "1.5"),
    "real-in-evidence-sid": ("evidence", "sid", "evid = 1", "1.25"),
}


@pytest.mark.parametrize("cell", UNENCODABLE.values(), ids=UNENCODABLE.keys())
def test_a_value_the_knowledge_hash_cannot_encode_is_refused(
    tmp_path: Path, cell: tuple[str, str, str, str]
) -> None:
    table, column, row, value = cell
    path = sealed(tmp_path)
    tamper(
        path,
        "PRAGMA ignore_check_constraints = ON",
        f"UPDATE {table} SET {column} = {value} WHERE {row}",
    )
    con = sqlite3.connect(path)
    query = f"SELECT typeof({column}) FROM {table} WHERE {row}"
    stored = con.execute(query).fetchone()
    con.close()
    assert stored in {("text",), ("blob",), ("real",)}  # stored as written, not converted
    assert stored != ("real",) or column != "confidence"
    refused(path, "section 3.6", f"column {column!r}")


def test_a_real_in_a_text_column_is_stored_as_text(tmp_path: Path) -> None:
    """A TEXT column converts a REAL to text (SQLite type affinity), so the file hashes."""
    path = sealed(tmp_path)
    tamper(path, "UPDATE node SET label = 1.5 WHERE nid = 1")
    con = sqlite3.connect(path)
    assert con.execute("SELECT typeof(label) FROM node WHERE nid = 1").fetchone() == ("text",)
    con.close()
    refused(path, "knowledge hash", "mismatch")


def test_derived_tables_are_not_hashed(tmp_path: Path) -> None:
    """``link_count`` and ``search`` are not hashed (section 3.6): the checker verifies them."""
    path = sealed(tmp_path)
    tamper(path, "UPDATE link_count SET count = count + 1")
    with open(path) as f:
        assert f.kind == "mosaic"


def _flip_first_bit(path: Path) -> None:
    con = sqlite3.connect(path, isolation_level=None)
    (bits,) = con.execute("SELECT bits FROM vector WHERE nid = 1").fetchone()
    flipped = bytes([bits[0] ^ 0x80]) + bits[1:]
    con.execute("UPDATE vector SET bits = ? WHERE nid = 1", (flipped,))
    con.close()


def test_tampered_vector_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    _flip_first_bit(path)
    refused(path, "vector hash", "mismatch")


def test_swapped_vectors_are_refused(tmp_path: Path) -> None:
    """The vector hash binds each vector to its node (section 3.7)."""
    path = sealed(tmp_path)
    tamper(
        path,
        "UPDATE vector SET nid = -1 WHERE nid = 1",
        "UPDATE vector SET nid = 1 WHERE nid = 2",
        "UPDATE vector SET nid = 2 WHERE nid = -1",
    )
    refused(path, "vector hash", "mismatch")


def test_short_vector_is_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(
        path,
        "PRAGMA ignore_check_constraints = ON",
        "UPDATE vector SET bits = X'00' WHERE nid = 1",
    )
    refused(path, "vector", "48-byte")


def test_removed_vectors_are_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    tamper(path, "DELETE FROM vector")
    refused(path, "vector hash", "mismatch")


def test_vectors_added_to_a_tessera_are_refused(tmp_path: Path) -> None:
    path = sealed(tmp_path, "tessera")
    tamper(path, f"INSERT INTO vector (nid, bits) VALUES (1, X'{'00' * 48}')")
    refused(path, "vector hash", "mismatch")


def test_a_refused_file_leaves_nothing_behind(tmp_path: Path) -> None:
    path = sealed(tmp_path)
    _flip_first_bit(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    refused(path, "vector hash")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert sorted(p.name for p in tmp_path.iterdir()) == ["file.db"]


# --- Bounded queries (section 3.8 step 4, section 10) --------------------------------------


def test_query_returns_rows_up_to_the_row_limit(tmp_path: Path) -> None:
    with open(sealed(tmp_path), limits=Limits(rows=18)) as f:
        assert len(f.query("SELECT id FROM node")) == 18


def test_query_over_the_row_limit_is_stopped(tmp_path: Path) -> None:
    with open(sealed(tmp_path), limits=Limits(rows=17)) as f:
        with pytest.raises(QueryLimitError, match="17 rows"):
            f.query("SELECT id FROM node")
        # The connection stays usable after a stopped query.
        assert f.query("SELECT count(*) FROM node") == [(18,)]


def test_limits_can_be_given_per_query(tmp_path: Path) -> None:
    with open(sealed(tmp_path)) as f:
        with pytest.raises(QueryLimitError, match="2 rows"):
            f.query("SELECT id FROM node", limits=Limits(rows=2))
        assert len(f.query("SELECT id FROM node")) == 18


ENDLESS = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c"


def test_query_over_the_time_limit_is_stopped(tmp_path: Path) -> None:
    with open(sealed(tmp_path), limits=Limits(seconds=0.05)) as f:
        with pytest.raises(QueryLimitError, match=r"0\.05 s"):
            f.query(ENDLESS)
        assert f.query("SELECT count(*) FROM node") == [(18,)]


def test_limits_have_defaults() -> None:
    limits = Limits()
    assert limits.seconds is not None and limits.seconds > 0
    assert limits.rows is not None and limits.rows > 0


@pytest.mark.parametrize("bad", [{"seconds": 0}, {"rows": 0}, {"seconds": -1.0}])
def test_limits_must_be_positive(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="limit"):
        Limits(**bad)  # ty: ignore[invalid-argument-type]


def test_limits_can_be_switched_off(tmp_path: Path) -> None:
    """A trusted caller, such as the builder reading its own pieces, may lift the bounds."""
    with open(sealed(tmp_path), limits=Limits(seconds=None, rows=None)) as f:
        assert len(f.query("SELECT id FROM node")) == 18
