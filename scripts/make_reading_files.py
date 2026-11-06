"""Write ``conformance/reading/``: files that the reading rules open or refuse (section 3.8).

Every reader, the Python one in ``mosaic_format`` and the TypeScript kit, must open the files
marked ``opens`` and return their header, and must refuse every other file for the rule it
breaks: ``sqlite``, ``application_id``, ``user_version``, ``format_version``, ``schema`` or
``header`` (section 3.8 step 2; sections 3.1, 3.3 and 9). Hashes are recomputed and written
back after each change, so a file breaks only its one rule; hash cases are not here.

Each file starts from the conforming tessera or mosaic of ``scripts/make_invalid_files.py``
(invented data). The script also writes ``cases.json`` (file name → whether it opens, the rule
it breaks, and the header a reader returns) and ``README.md``. Run it from the repository
root::

    uv run python scripts/make_reading_files.py [--out DIR]

It replaces only the files it writes itself.
"""

import argparse
import importlib.util
import json
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from mosaic_format import seal

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "conformance" / "reading"


def _load_invalid_files() -> ModuleType:
    path = Path(__file__).resolve().parent / "make_invalid_files.py"
    spec = importlib.util.spec_from_file_location("make_invalid_files", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("make_invalid_files", module)
    spec.loader.exec_module(module)
    return module


mif = _load_invalid_files()

PIECE = "tessera.tessera"
"""The conforming tessera; its knowledge hash pins the first piece of every mosaic here."""

RULES: dict[str, str] = {
    "sqlite": "The file is not a SQLite 3 database (section 3.1)",
    "application_id": "`PRAGMA application_id` is not `0x4D4F5341` (MOSA) (section 3.1)",
    "user_version": "`PRAGMA user_version` is not 1, that of format 0.1 (sections 3.1 and 9)",
    "format_version": (
        "The header's `format_version` is one the reader does not implement, a newer minor "
        "version included (sections 3.8 step 2 and 9)"
    ),
    "schema": "The schema is not exactly the objects of `format.sql` (section 3.1)",
    "header": "The header is not exactly one row of a known kind (section 3.3)",
}
"""Each rule a refused file breaks, by the name ``cases.json`` gives it."""


@dataclass(frozen=True)
class Case:
    """One file: its name, the rule it breaks (``None`` when it opens), and how it is made."""

    name: str
    rule: str | None
    made_by: str
    make: Callable[[Path, str], None]
    """Writes the file at the given path; the second argument is the hash of the piece."""


def _bytes(data: bytes) -> Callable[[Path, str], None]:
    def make(path: Path, _: str) -> None:
        path.write_bytes(data)

    return make


def _mosaic(before: list[str] | None = None, after: list[str] | None = None):
    return mif._changed(mif.mosaic, before or [], after or [])


CASES: tuple[Case, ...] = (
    Case(PIECE, None, "The conforming tessera", mif._sealed(mif._tessera)),
    Case(
        "mosaic.mosaic",
        None,
        "The conforming mosaic, with vectors, whose first piece is `tessera.tessera`",
        mif._sealed(mif.mosaic),
    ),
    Case(
        "empty.mosaic",
        "application_id",
        "An empty file, which SQLite opens as an empty database",
        _bytes(b""),
    ),
    Case(
        "not-sqlite.mosaic",
        "sqlite",
        "A text file, not a SQLite database",
        _bytes(b"This is not a SQLite database.\n" * 200),
    ),
    Case(
        "application-id.mosaic",
        "application_id",
        "`application_id` is 0",
        _mosaic(after=["PRAGMA application_id = 0"]),
    ),
    Case(
        "user-version.mosaic",
        "user_version",
        "`user_version` is 2",
        _mosaic(after=["PRAGMA user_version = 2"]),
    ),
    Case(
        "format-version.mosaic",
        "format_version",
        "The header's `format_version` is `0.2`",
        _mosaic(["UPDATE header SET format_version = '0.2'"]),
    ),
    Case(
        "newer-minor.mosaic",
        "format_version",
        "A newer minor version: `format_version` is `0.2` and the header has an added column; "
        "refused for its version, not its schema",
        _mosaic(
            ["ALTER TABLE header ADD COLUMN extra TEXT", "UPDATE header SET format_version = '0.2'"]
        ),
    ),
    Case(
        "header-column.mosaic",
        "schema",
        "The header has an added column, but `format_version` is `0.1`",
        _mosaic(["ALTER TABLE header ADD COLUMN extra TEXT"]),
    ),
    Case(
        "schema-extra-table.mosaic",
        "schema",
        "A table that `format.sql` does not define",
        _mosaic(["CREATE TABLE extra (a)"]),
    ),
    Case(
        "schema-dropped-index.mosaic",
        "schema",
        "The index `edge_in` of `format.sql` is dropped",
        _mosaic(["DROP INDEX edge_in"]),
    ),
    Case(
        "no-header.mosaic",
        "header",
        "The header row is deleted",
        _mosaic(["DELETE FROM header"]),
    ),
    Case(
        "header-kind.mosaic",
        "header",
        "The header's `kind` is `other`",
        _mosaic(["UPDATE header SET kind = 'other'"]),
    ),
)
"""Every file, in the order the README lists them."""


def header_of(path: Path) -> dict[str, object]:
    """The header row of a file that opens, as ``cases.json`` records it."""
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        cursor = con.execute("SELECT * FROM header")
        names = [d[0] for d in cursor.description]
        (row,) = cursor.fetchall()
        return dict(zip(names, row, strict=True))
    finally:
        con.close()


README_HEAD = """\
# Reading cases

Files that the reading rules of section 3.8 open or refuse. Every reader (the Python reader in
`mosaic_format` and the TypeScript kit) opens each file whose `opens` is true in `cases.json`
and returns its header as `cases.json` records it, and refuses every other file for the rule it
names, with an error that names the file and what failed.

Generated by `scripts/make_reading_files.py` from the conforming files of
`scripts/make_invalid_files.py` (invented data). Hashes are rewritten after each change, so a
file breaks only its one rule. `mosaic check` passes the files that open (`mosaic.mosaic` with
`{piece}` as its piece) and fails the others.

| File | Rule | Made by |
| --- | --- | --- |
"""


def readme() -> str:
    lines = [README_HEAD.format(piece=PIECE)]
    for case in CASES:
        rule = "opens" if case.rule is None else f"`{case.rule}`"
        lines.append(f"| `{case.name}` | {rule} | {case.made_by} |\n")
    lines.append("\nRules:\n\n")
    for rule, text in RULES.items():
        lines.append(f"- `{rule}`: {text}\n")
    return "".join(lines)


def cases_json(out: Path) -> str:
    data: dict[str, dict[str, object]] = {}
    for case in CASES:
        entry: dict[str, object] = {"opens": case.rule is None, "rule": case.rule}
        if case.rule is None:
            entry["header"] = header_of(out / case.name)
        data[case.name] = entry
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def outputs() -> list[str]:
    """The names of every file the script writes."""
    return [*(c.name for c in CASES), "cases.json", "README.md"]


def write(out: Path) -> None:
    """Write every file into ``out``, replacing only the files this script writes."""
    out.mkdir(parents=True, exist_ok=True)
    for name in outputs():
        (out / name).unlink(missing_ok=True)
    piece_hash = seal(out / PIECE, mif.tessera()).knowledge_hash
    for case in CASES:
        if case.name != PIECE:
            case.make(out / case.name, piece_hash)
    (out / "cases.json").write_text(cases_json(out), "utf-8", newline="\n")
    (out / "README.md").write_text(readme(), "utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help=f"directory (default {OUT})")
    args = parser.parse_args(argv)
    write(args.out)
    print(f"wrote {len(CASES)} files, cases.json and README.md to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
