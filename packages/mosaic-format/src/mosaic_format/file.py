"""Create new, empty tesserae and mosaics (Specification 0.1, section 3.1)."""

import os
import sqlite3
from pathlib import Path

from mosaic_format import KINDS
from mosaic_format.schema import format_sql

SIDECARS = ("-journal", "-wal", "-shm")


def create(path: str | os.PathLike[str], kind: str) -> Path:
    """Create a new empty file at ``path`` for the ``kind`` profile and return its path.

    The file is one SQLite 3 database with ``application_id`` and ``user_version`` of format
    0.1, page size 4096, ``journal_mode=DELETE`` and exactly the objects of ``format.sql``;
    no journal or write-ahead log is left beside it. Both profiles share the schema, so the
    file is the same for either ``kind``; the header row that records the kind is written
    when the file is sealed. An existing file is never overwritten.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
    target = Path(path)
    for suffix in SIDECARS:
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            raise FileExistsError(f"{sidecar}: a journal is in the way of {target.name}")
    sql = format_sql()
    # Claim the name atomically: O_EXCL fails on any existing entry, a dangling symbolic link
    # included, so no other file is ever opened, written or, on failure, removed.
    try:
        os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666))
    except FileExistsError:
        raise FileExistsError(f"{target}: already exists; create never overwrites a file") from None
    try:
        con = sqlite3.connect(target, isolation_level=None)  # an empty file is a new database
        try:
            mode = con.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
            if mode != "delete":
                raise sqlite3.OperationalError(f"{target}: journal_mode is {mode!r}, not 'delete'")
            con.executescript(sql)
        finally:
            con.close()
    except BaseException:
        # Only the file claimed above and the journals it made, which did not exist before.
        for leftover in [target, *(target.with_name(target.name + s) for s in SIDECARS)]:
            leftover.unlink(missing_ok=True)
        raise
    return target
