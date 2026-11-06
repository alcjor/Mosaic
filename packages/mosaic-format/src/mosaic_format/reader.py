"""Open tesserae and mosaics by the reading rules (Specification 0.1, section 3.8).

:func:`open` returns a :class:`SealedFile` only after every check has passed:

1. the file is opened read-only and immutable, and no journal or write-ahead log lies beside
   it (section 3.1);
2. text is stored as UTF-8 (section 3.1, decision B on #104: a file in UTF-16 is refused);
   ``application_id`` and ``user_version`` are those of format 0.1, the header's
   ``format_version`` is one this reader implements (only ``0.1``; a newer minor version is
   refused too, section 9), the schema holds exactly the objects of ``format.sql`` with the same
   definitions (``sqlite_stat1`` and ``sqlite_stat4`` may be present), and the header is one row
   of a known kind. The version is read before the schema is compared whenever ``header`` is a
   plain table with a stored ``format_version`` column, so a newer minor version that adds a
   column to ``header`` is refused for its version, not as a schema mismatch;
3. the knowledge hash (section 3.6) and the vector hash (section 3.7) are recomputed and must
   equal the header's. A value either hash cannot encode (``CHECK`` constraints are not
   re-checked on open, so a crafted file can hold, say, a ``confidence`` that is not REAL) is
   refused too.

Anything else is refused with :class:`FileRefusedError`, naming the file and what failed.

Every value in the file is untrusted data (section 10). Queries run through
:meth:`SealedFile.query`, which allows only reads, and are bounded in time and in the number of
rows returned (:class:`Limits`). The defaults are this reader's, not the specification's, which
sets no numbers.
"""

import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Self

from mosaic_format import APPLICATION_ID, FORMAT_VERSION, KINDS, USER_VERSION
from mosaic_format.file import SIDECARS
from mosaic_format.hashes import knowledge_hash, vector_hash
from mosaic_format.schema import format_sql

IMPLEMENTED_VERSIONS = (FORMAT_VERSION,)
"""Format versions this reader implements (section 9)."""

STATISTICS = {
    "sqlite_stat1": "CREATE TABLE sqlite_stat1(tbl,idx,stat)",
    "sqlite_stat4": "CREATE TABLE sqlite_stat4(tbl,idx,neq,nlt,ndlt,sample)",
}
"""SQLite's statistics tables, which ``ANALYZE`` writes; the only extra objects allowed."""

PROGRESS_STEPS = 1000
"""Virtual-machine steps between two checks of a query's deadline."""

_ALLOWED_ACTIONS = frozenset(
    {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
)
_READ_PRAGMAS = frozenset({"data_version"})


class FileRefusedError(ValueError):
    """A file that the reading rules of section 3.8 refuse."""


class QueryLimitError(RuntimeError):
    """A query stopped because it ran too long or returned too many rows."""


@dataclass(frozen=True)
class Limits:
    """Bounds on one query (section 3.8 step 4). ``None`` lifts a bound, for trusted callers."""

    seconds: float | None = 1.0
    """Longest a query may run, fetching its rows included."""
    rows: int | None = 10_000
    """Most rows a query may return."""

    def __post_init__(self) -> None:
        if self.seconds is not None and not self.seconds > 0:
            raise ValueError(f"time limit must be positive seconds or None, not {self.seconds!r}")
        if self.rows is not None and not self.rows > 0:
            raise ValueError(f"row limit must be a positive number or None, not {self.rows!r}")


def _refuse(path: Path, reason: str) -> FileRefusedError:
    return FileRefusedError(f"{path}: {reason}")


@cache
def _reference_schema() -> frozenset[tuple[str, str, str, str | None]]:
    """``sqlite_schema`` of a fresh database made from ``format.sql``: what a file must hold."""
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(format_sql())
        return frozenset(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema"))
    finally:
        con.close()


def _check_schema(path: Path, con: sqlite3.Connection) -> None:
    """Exactly the objects of ``format.sql``, with the same definitions (section 3.1)."""
    expected = _reference_schema()
    actual = {
        row
        for row in con.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema")
        if not (row[0] == "table" and STATISTICS.get(row[1]) == row[3])
    }
    expected_names = {(t, n) for t, n, _, _ in expected}
    actual_names = {(t, n) for t, n, _, _ in actual}
    problems: list[str] = []
    for t, n in sorted(expected_names - actual_names):
        problems.append(f"{t} {n} is missing")
    for t, n in sorted(actual_names - expected_names):
        problems.append(f"{t} {n} is not in format.sql")
    for t, n in sorted(expected_names & actual_names):
        want = {r for r in expected if (r[0], r[1]) == (t, n)}
        have = {r for r in actual if (r[0], r[1]) == (t, n)}
        if want != have:
            problems.append(f"{t} {n} differs from its definition in format.sql")
    if problems:
        listed = "; ".join(problems)
        raise _refuse(path, f"schema does not match format.sql (section 3.1): {listed}")


def _check_version(path: Path, con: sqlite3.Connection) -> None:
    """Refuse a format version this reader does not implement (sections 3.8 step 2 and 9)."""
    implemented = ", ".join(IMPLEMENTED_VERSIONS)
    (user_version,) = con.execute("PRAGMA user_version").fetchone()
    if user_version != USER_VERSION:
        raise _refuse(
            path,
            f"user_version {user_version}: this reader implements format version {implemented} "
            f"(user_version {USER_VERSION}) only and refuses any other (section 9)",
        )
    if not _has_stored_format_version(con):
        return
    # The header of format.sql holds one row; read at most two of a crafted table, so a file
    # with millions of rows cannot cost memory or time here (section 10). Any extra row is a
    # schema mismatch, which the schema check names.
    for (version,) in con.execute("SELECT format_version FROM header LIMIT 2"):
        if version not in IMPLEMENTED_VERSIONS:
            raise _refuse(
                path,
                f"format version {version!r} is not implemented by this reader, which reads "
                f"{implemented} only; a newer minor version is refused too (section 9)",
            )


def _has_stored_format_version(con: sqlite3.Connection) -> bool:
    """Whether ``header`` is a plain table with a stored ``format_version`` column.

    Only then is the version read before the schema check. A newer minor version may add a
    column to ``header`` (section 9), so the table need not match ``format.sql`` exactly; it is
    then refused for its version, not as a schema mismatch. A crafted ``header`` that is a view,
    a virtual table or a computed column could be endless or costly (section 10): it is left to
    the schema check, which names what is wrong.
    """
    query = "SELECT type, sql FROM sqlite_schema WHERE name = 'header'"
    rows = con.execute(query).fetchall()
    if len(rows) != 1:
        return False
    (kind, sql) = rows[0]
    if kind != "table" or not isinstance(sql, str) or not sql.startswith("CREATE TABLE "):
        return False
    columns = con.execute("SELECT name, hidden FROM pragma_table_xinfo('header')").fetchall()
    return ("format_version", 0) in columns


def _read_header(path: Path, con: sqlite3.Connection) -> dict[str, object]:
    """The one header row (section 3.3), with a kind this reader knows."""
    # CHECK (one = 1) is not enforced on read, so a crafted header can hold any number of rows:
    # read at most two, so it costs nothing to refuse (section 10).
    cursor = con.execute("SELECT * FROM header LIMIT 2")
    names = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if len(rows) != 1:
        found = "0 rows" if not rows else "2 rows or more"
        raise _refuse(path, f"header has {found}; it must hold exactly one (section 3.3)")
    header = dict(zip(names, rows[0], strict=True))
    if header["one"] != 1:
        raise _refuse(path, f"header row has one = {header['one']!r}, not 1 (section 3.3)")
    if header["kind"] not in KINDS:
        raise _refuse(path, f"header kind {header['kind']!r} is not one of {KINDS} (section 3.3)")
    return header


def _check_hashes(path: Path, con: sqlite3.Connection, header: Mapping[str, object]) -> None:
    """Recompute both hashes and compare them with the header's (section 3.8 step 3)."""
    try:
        knowledge = knowledge_hash(con)
    except (ValueError, TypeError) as e:
        raise _refuse(path, f"{e} (section 3.6)") from None
    if knowledge != header["knowledge_hash"]:
        raise _refuse(
            path,
            f"knowledge hash mismatch: the header says {header['knowledge_hash']!r}, the "
            f"content gives {knowledge!r} (section 3.6)",
        )
    try:
        vectors = vector_hash(con)
    except ValueError as e:
        raise _refuse(path, f"{e} (section 3.7)") from None
    if vectors != header["vector_hash"]:
        raise _refuse(
            path,
            f"vector hash mismatch: the header says {header['vector_hash']!r}, the vectors "
            f"give {vectors!r} (section 3.7)",
        )


def _authorize(action: int, arg1: str | None, arg2: str | None, *_: object) -> int:
    """Allow reads only; FTS5 itself reads ``PRAGMA data_version`` while it searches."""
    if action in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg1 in _READ_PRAGMAS and arg2 is None:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _connect(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-only and immutable (section 3.8 step 1); nothing is ever written."""
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        con.execute("PRAGMA query_only = ON")
        con.execute("PRAGMA trusted_schema = OFF")
        con.execute("PRAGMA cell_size_check = ON")
    except BaseException:
        con.close()
        raise
    return con


SQLITE_MAGIC = b"SQLite format 3\x00"
"""The 16 bytes that open every SQLite 3 database file."""

_UTF16 = {2: "UTF-16le", 3: "UTF-16be"}
"""Text encodings of the SQLite header (bytes 56 to 59) other than UTF-8 (1)."""


def _check_encoding_bytes(path: Path) -> None:
    """Refuse a file whose SQLite header says its text is UTF-16, before SQLite reads it.

    The kit reads these bytes too, so both readers name the encoding even when the rest of the
    file does not match its header (section 3.1, decision B on #104).
    """
    with path.open("rb") as f:
        head = f.read(100)
    if len(head) == 100 and head.startswith(SQLITE_MAGIC):
        encoding = _UTF16.get(int.from_bytes(head[56:60], "big"))
        if encoding is not None:
            raise _refuse(
                path,
                f"text encoding {encoding}: a tessera or mosaic stores its text as UTF-8 "
                f"(section 3.1)",
            )


def _check_encoding(path: Path, con: sqlite3.Connection) -> None:
    """Text is stored as UTF-8 (section 3.1, decision B on #104)."""
    (encoding,) = con.execute("PRAGMA encoding").fetchone()
    if encoding != "UTF-8":
        raise _refuse(
            path,
            f"text encoding {encoding}: a tessera or mosaic stores its text as UTF-8 (section 3.1)",
        )


def _verify(path: Path, con: sqlite3.Connection) -> dict[str, object]:
    _check_encoding(path, con)
    (application_id,) = con.execute("PRAGMA application_id").fetchone()
    if application_id != APPLICATION_ID:
        raise _refuse(
            path,
            f"application_id 0x{application_id & 0xFFFFFFFF:08X} is not "
            f"0x{APPLICATION_ID:08X} (MOSA): not a tessera or mosaic (section 3.1)",
        )
    _check_version(path, con)
    _check_schema(path, con)
    header = _read_header(path, con)
    _check_hashes(path, con, header)
    return header


class SealedFile:
    """A tessera or mosaic that passed the reading rules, open read-only for bounded queries."""

    def __init__(
        self, path: Path, con: sqlite3.Connection, header: Mapping[str, object], limits: Limits
    ) -> None:
        self.path = path
        self.header: Mapping[str, object] = MappingProxyType(dict(header))
        self.limits = limits
        self._con = con

    @property
    def kind(self) -> str:
        return str(self.header["kind"])

    @property
    def format_version(self) -> str:
        return str(self.header["format_version"])

    @property
    def knowledge_hash(self) -> str:
        return str(self.header["knowledge_hash"])

    @property
    def vector_hash(self) -> str | None:
        value = self.header["vector_hash"]
        return None if value is None else str(value)

    @property
    def embed_model(self) -> str | None:
        value = self.header["embed_model"]
        return None if value is None else str(value)

    def query(
        self, sql: str, params: Sequence[object] = (), *, limits: Limits | None = None
    ) -> list[tuple[object, ...]]:
        """Run one read-only statement and return its rows, within ``limits``.

        Only reads are authorised: a statement that writes, attaches a database or sets a
        pragma fails with :class:`sqlite3.DatabaseError`. A query that runs past the time limit
        or returns more rows than the row limit raises :class:`QueryLimitError`.
        """
        bounds = limits or self.limits
        con = self._con
        deadline = None if bounds.seconds is None else time.monotonic() + bounds.seconds
        stopped = False

        def progress() -> int:
            nonlocal stopped
            stopped = deadline is not None and time.monotonic() > deadline
            return 1 if stopped else 0

        con.set_authorizer(_authorize)
        if deadline is not None:
            con.set_progress_handler(progress, PROGRESS_STEPS)
        try:
            cursor = con.execute(sql, tuple(params))
            try:
                if bounds.rows is None:
                    return cursor.fetchall()
                rows = cursor.fetchmany(bounds.rows + 1)
            finally:
                cursor.close()
        except sqlite3.OperationalError:
            if stopped:
                raise QueryLimitError(
                    f"{self.path}: query stopped after the time limit of {bounds.seconds} s"
                ) from None
            raise
        finally:
            con.set_progress_handler(None, 0)
            con.set_authorizer(None)
        if len(rows) > bounds.rows:
            raise QueryLimitError(
                f"{self.path}: query returned more than the row limit of {bounds.rows} rows"
            )
        return rows

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def open(path: str | Path, *, limits: Limits | None = None) -> SealedFile:
    """Open a tessera or mosaic by the reading rules of section 3.8, or refuse it.

    Raises :class:`FileNotFoundError` when there is no file at ``path`` and
    :class:`FileRefusedError` when the file breaks a rule; the message names the file and the
    rule. ``limits`` bound every later query (default :class:`Limits`).
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"{target}: no such file")
    for suffix in SIDECARS:
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            raise _refuse(
                target,
                f"{sidecar.name} lies beside it; a sealed file has no journal or "
                f"write-ahead log (section 3.1)",
            )
    _check_encoding_bytes(target)
    con = _connect(target)
    try:
        header = _verify(target, con)
    except FileRefusedError:
        con.close()
        raise
    except sqlite3.DatabaseError as e:
        con.close()
        raise _refuse(target, f"not a readable SQLite 3 database ({e}) (section 3.1)") from None
    except BaseException:
        con.close()
        raise
    return SealedFile(target, con, header, limits or Limits())
