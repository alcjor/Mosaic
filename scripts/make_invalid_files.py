"""Write ``conformance/invalid/files/``: one invalid tessera or mosaic per invariant and rule.

Section 11 of the specification asks for "invalid files, one per invariant in section 3.9",
which a checker rejects naming the invariant. Each file here starts from a conforming tessera
or mosaic (:func:`tessera` and :func:`mosaic`, all data invented) and breaks one rule:

- through the sealed writer, when the writer accepts the content (it leaves most rules to the
  schema and the checker);
- otherwise by changing the sealed file with plain SQL, with CHECK constraints and foreign keys
  off where the rule cannot be broken without them, and then writing the knowledge and vector
  hash of the changed content back into the header, so the file breaks nothing else.

The script also writes ``cases.json`` (file name → the rules a checker must name, and the piece
files to give it) and ``README.md``. Run it from the repository root::

    uv run python scripts/make_invalid_files.py [--out DIR]

It replaces only the files it writes itself.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from mosaic_format import seal
from mosaic_format.hashes import knowledge_hash, vector_hash
from mosaic_format.writer import (
    Alias,
    Content,
    Edge,
    EdgeKey,
    Evidence,
    ExternalRef,
    Header,
    Mention,
    Node,
    Source,
    Type,
    Vector,
)

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "conformance" / "invalid" / "files"
PRODUCER = "make-invalid-files/0.1"
PIECE = "inv-15-piece.tessera"
"""The piece file the inv-15 case is checked with: the conforming tessera."""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


DOC_HASH = _hash("items.csv")
NOTES_HASH = _hash("notes.txt")
INNER_HASH = _hash("inner mosaic")
PATTERN_HASH = _hash("pattern.yaml")
MODEL = "invented-model@" + _hash("model file")
DOC_NOTICE = "CC0-1.0"
NOTES_NOTICE = "Invented for the conformance suite"


# --- conforming content -----------------------------------------------------------------------


def tessera() -> Content:
    """A conforming tessera: one CSV-like source, two rows, a group, a mention."""
    row1, row2, group = "Row:1", "Row:2", "Group:x"
    edge = EdgeKey(row1, "in_group", group)
    return Content(
        header=Header(kind="tessera", producer=PRODUCER),
        sources=[Source(id="doc", kind="file", hash=DOC_HASH, path="items.csv", notice=DOC_NOTICE)],
        types=[
            Type(
                name="Row",
                kind="node",
                description="One row",
                props='{"code":"text","size":"integer"}',
            ),
            Type(name="Group", kind="node"),
            Type(name="in_group", kind="edge", from_type="Row", to_type="Group"),
        ],
        nodes=[
            Node(id=row1, type="Row", key="1", label="Row one", props='{"code":"a","size":1}'),
            Node(id=row2, type="Row", key="2", label="Row two", summary="The second row"),
            Node(id=group, type="Group", key="x", label="Group x"),
        ],
        edges=[Edge(type="in_group", src=row1, dst=group)],
        aliases=[Alias(text="one", node=row1, origin="source")],
        evidence=[
            Evidence(row1, "doc", "row=1", "extracted", PRODUCER, snippet="a,1,x"),
            Evidence(row1, "doc", "row=1;field=size", "inferred", "guess/1", "size", 0.5),
            Evidence(row2, "doc", "row=2", "extracted", PRODUCER, snippet="b,2,"),
            Evidence(group, "doc", "row=1;field=group", "extracted", PRODUCER, snippet="x"),
            Evidence(edge, "doc", "row=1;field=group", "extracted", PRODUCER),
        ],
        mentions=[Mention("x", "row=2;field=note", row2, "csv.note", "identifier")],
        external_refs=[ExternalRef(row1, "store", "record", '{"id":"1"}', "doc")],
    )


def mosaic(piece_hash: str) -> Content:
    """A conforming mosaic of two pieces: the tessera (``first``) and a mosaic (``inner``).

    Its ``source`` holds one row per piece and every original source of every piece, with the
    id prefixed by the piece name (decision on #9 and #66); evidence names original sources
    only, and evidence that passed through ``inner`` lists its hash in ``via``.
    """
    a, b, x = "Item:a", "Item:b", "Group:x"
    via = json.dumps([INNER_HASH])
    nodes = [
        Node(id=a, type="Item", key="a", label="Item A", props='{"code":"a","size":1}'),
        Node(id=b, type="Item", key="b", label="Item B", summary="Second", props='{"code":"b"}'),
        Node(id=x, type="Group", key="x", label="Group x", props='{"name":"x"}'),
    ]
    return Content(
        header=Header(
            kind="mosaic",
            producer=PRODUCER,
            pattern_hash=PATTERN_HASH,
            target="all",
            embed_model=MODEL,
        ),
        sources=[
            Source(id="first", kind="tessera", hash=piece_hash, path="first.tessera"),
            Source(id="first/doc", kind="file", hash=DOC_HASH, path="items.csv", notice=DOC_NOTICE),
            Source(id="inner", kind="mosaic", hash=INNER_HASH, path="inner.mosaic"),
            Source(id="inner/base/notes", kind="file", hash=NOTES_HASH, notice=NOTES_NOTICE),
        ],
        types=[
            Type(
                name="Item",
                kind="node",
                key_prop="code",
                props='{"code":"text","size":"integer"}',
            ),
            Type(name="Group", kind="node", key_prop="name", props='{"name":"text"}'),
            Type(name="in_group", kind="edge", from_type="Item", to_type="Group"),
        ],
        nodes=nodes,
        edges=[Edge(type="in_group", src=a, dst=x), Edge(type="in_group", src=b, dst=x)],
        aliases=[Alias("A", a, "source"), Alias("item-b", b, "pattern")],
        evidence=[
            Evidence(a, "first/doc", "row=1", "extracted", PRODUCER, snippet="a,1,x"),
            Evidence(a, "first/doc", "row=1;field=size", "inferred", "guess/1", "size", 0.5),
            Evidence(b, "inner/base/notes", "line=2", "extracted", PRODUCER, via=via, snippet="b"),
            Evidence(x, "first/doc", "row=1;field=group", "extracted", PRODUCER, snippet="x"),
            Evidence(
                EdgeKey(a, "in_group", x), "first/doc", "row=1;field=group", "extracted", PRODUCER
            ),
            Evidence(
                EdgeKey(b, "in_group", x),
                "inner/base/notes",
                "line=3",
                "extracted",
                PRODUCER,
                via=via,
            ),
        ],
        external_refs=[ExternalRef(a, "store", "record", '{"id":"a"}', "first/doc")],
        vectors=[Vector(n.id, bytes([i + 1]) * 48) for i, n in enumerate(nodes)],
    )


# --- ways to break a file ---------------------------------------------------------------------


def tamper(path: Path, before: Sequence[str] = (), after: Sequence[str] = ()) -> None:
    """Change a sealed file with SQL, constraints off; rehash between ``before`` and ``after``.

    The knowledge and vector hash of the changed content are written back into the header, so
    the file breaks only what the statements break. ``after`` runs once that is done.
    """
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("PRAGMA ignore_check_constraints = ON")
        for statement in before:
            con.execute(statement)
        con.execute(
            "UPDATE header SET knowledge_hash = ?, vector_hash = ?",
            (knowledge_hash(con), vector_hash(con)),
        )
        for statement in after:
            con.execute(statement)
        con.execute("VACUUM")
    finally:
        con.close()


@dataclass(frozen=True)
class Case:
    """One invalid file: its name, the rules a checker names, and how it is made."""

    name: str
    rules: tuple[str, ...]
    broken_by: str
    make: Callable[[Path, str], None]
    """Writes the file at the given path; the second argument is the hash of the piece."""
    pieces: tuple[str, ...] = ()


def _sealed(content: Callable[[str], Content]) -> Callable[[Path, str], None]:
    def make(path: Path, piece_hash: str) -> None:
        seal(path, content(piece_hash))

    return make


def _changed(
    base: Callable[[str], Content], before: Sequence[str] = (), after: Sequence[str] = ()
) -> Callable[[Path, str], None]:
    def make(path: Path, piece_hash: str) -> None:
        seal(path, base(piece_hash))
        tamper(path, before, after)

    return make


def _tessera(_: str) -> Content:
    return tessera()


def _with(base: Callable[[str], Content], **changes: object) -> Callable[[str], Content]:
    """``base`` with some of its lists extended (``+name``) or replaced (``name``)."""

    def content(piece_hash: str) -> Content:
        c = base(piece_hash)
        fields: dict[str, object] = {}
        for name, value in changes.items():
            if name.startswith("add_"):
                field = name.removeprefix("add_")
                fields[field] = [*getattr(c, field), *value]  # ty: ignore[not-iterable]
            else:
                fields[name] = value
        return replace(c, **fields)

    return content


def _notice_lost(piece_hash: str) -> Content:
    c = mosaic(piece_hash)
    sources = [replace(s, notice=None) if s.id == "first/doc" else s for s in c.sources]
    return replace(c, sources=sources)


def _type_props(_: str) -> Content:
    c = tessera()
    types = [replace(t, props='{"code":"string"}') if t.name == "Row" else t for t in c.types]
    return replace(c, types=types)


ZERO = "0" * 64
MAX_EVID = "(SELECT max(evid) FROM evidence)"

CASES: tuple[Case, ...] = (
    Case(
        "inv-1-no-header.tessera",
        ("inv-1",),
        "The header row is deleted",
        _changed(_tessera, ["DELETE FROM header"]),
    ),
    Case(
        "inv-1-version.tessera",
        ("inv-1", "constraint"),
        "`format_version` is `0.2` (format.sql's CHECK allows only `0.1`)",
        _changed(_tessera, ["UPDATE header SET format_version = '0.2'"]),
    ),
    Case(
        "inv-2-no-evidence.tessera",
        ("inv-2",),
        "A node with no evidence row",
        _sealed(_with(_tessera, add_nodes=[Node(id="Row:3", type="Row", key="3")])),
    ),
    Case(
        "inv-3-extracted-confidence.tessera",
        ("inv-3", "constraint"),
        "An extracted evidence row with a confidence (format.sql's CHECK forbids it)",
        _changed(
            _tessera,
            ["UPDATE evidence SET confidence = 0.5 WHERE locator = 'row=2'"],
        ),
    ),
    Case(
        "inv-4-edge-ends.tessera",
        ("inv-4",),
        "An `in_group` edge from a `Group` to a `Row`, reversing the declared ends",
        _sealed(
            _with(
                _tessera,
                add_edges=[Edge(type="in_group", src="Group:x", dst="Row:2")],
                add_evidence=[
                    Evidence(
                        EdgeKey("Group:x", "in_group", "Row:2"),
                        "doc",
                        "row=2;field=group",
                        "extracted",
                        PRODUCER,
                    )
                ],
            )
        ),
    ),
    Case(
        "inv-5-dangling-edge.tessera",
        ("inv-5", "constraint"),
        "An edge whose target is no node of the file (its foreign key fails)",
        _changed(_tessera, ["UPDATE edge SET dst = 99"]),
    ),
    Case(
        "inv-6-hash.tessera",
        ("inv-6",),
        "The header's knowledge hash is not that of the content",
        _changed(_tessera, after=[f"UPDATE header SET knowledge_hash = '{ZERO}'"]),
    ),
    Case(
        "inv-6-order.mosaic",
        ("inv-6",),
        "The only `external_ref` row has `xid` 2: row ids are not dense",
        _changed(mosaic, ["UPDATE external_ref SET xid = 2"]),
    ),
    Case(
        "inv-7-two-sources.tessera",
        ("inv-7",),
        "A tessera with two sources",
        _sealed(_with(_tessera, add_sources=[Source(id="doc2", kind="file", hash=NOTES_HASH)])),
    ),
    Case(
        "inv-10-id-form.mosaic",
        ("inv-10",),
        "A node `Item:z` whose key is `zz`",
        _sealed(
            _with(
                mosaic,
                add_nodes=[Node(id="Item:z", type="Item", key="zz", label="Item Z")],
                add_evidence=[Evidence("Item:z", "first/doc", "row=9", "extracted", PRODUCER)],
                add_vectors=[Vector("Item:z", bytes([9]) * 48)],
            )
        ),
    ),
    Case(
        "inv-11-piece-hash.mosaic",
        ("inv-11", "constraint"),
        "Piece `first` with hash `abc123` (format.sql's CHECK wants 64 hex characters)",
        _changed(mosaic, ["UPDATE source SET hash = 'abc123' WHERE id = 'first'"]),
    ),
    Case(
        "inv-12-piece-source.mosaic",
        ("inv-12",),
        "An evidence row whose source is piece `first`, not an original source",
        _sealed(
            _with(
                mosaic,
                add_evidence=[Evidence("Item:a", "first", "row=1", "extracted", "other/1")],
            )
        ),
    ),
    Case(
        "inv-13-link-count.mosaic",
        ("inv-13",),
        "The `in` count of `Group:x` is 3; it has 2 `in_group` edges",
        _changed(
            mosaic,
            [
                "UPDATE link_count SET count = 3 WHERE direction = 'in' "
                "AND nid = (SELECT nid FROM node WHERE id = 'Group:x')"
            ],
        ),
    ),
    Case(
        "inv-14-vector-hash.mosaic",
        ("inv-14",),
        "The header's vector hash is not that of the vectors",
        _changed(mosaic, after=[f"UPDATE header SET vector_hash = '{ZERO}'"]),
    ),
    Case(
        "inv-15-notice.mosaic",
        ("inv-15",),
        f"Source `first/doc` without the notice of piece `{PIECE}`; checked with that piece",
        _sealed(_notice_lost),
        pieces=(PIECE,),
    ),
    Case(
        "evidence-duplicate.mosaic",
        ("evidence-duplicate",),
        "Two evidence rows equal in every column but `evid`",
        _changed(
            mosaic,
            [
                f"INSERT INTO evidence SELECT evid + 1, nid, eid, prop, sid, locator, method, "
                f"producer, confidence, via FROM evidence WHERE evid = {MAX_EVID}"
            ],
        ),
    ),
    Case(
        "text-nul.tessera",
        ("text-nul",),
        "A type description holding U+0000",
        _changed(
            _tessera,
            ["UPDATE type SET description = 'One' || char(0) || 'row' WHERE name = 'Row'"],
        ),
    ),
    Case(
        "canonical-json.tessera",
        ("canonical-json",),
        "Node properties written with spaces, not in RFC 8785 canonical form",
        _changed(
            _tessera,
            ['UPDATE node SET props = \'{"code": "a", "size": 1}\' WHERE id = \'Row:1\''],
        ),
    ),
    Case(
        "search.tessera",
        ("search",),
        "A `search` row for a node that does not exist",
        _changed(_tessera, ["INSERT INTO search (rowid, label) VALUES (99, 'stray')"]),
    ),
    Case(
        "profile.tessera",
        ("profile",),
        "A tessera with a `link_count` row",
        _changed(_tessera, ["INSERT INTO link_count VALUES (1, 'in_group', 'out', 1)"]),
    ),
    Case(
        "type-props.tessera",
        ("type-props",),
        "A declared property of kind `string`",
        _sealed(_type_props),
    ),
    Case(
        "container.tessera",
        ("container",),
        "`application_id` is 0",
        _changed(_tessera, after=["PRAGMA application_id = 0"]),
    ),
    Case(
        "constraint.tessera",
        ("constraint",),
        "The header's producer is `nobody`, not `name/version` (format.sql's CHECK)",
        _changed(_tessera, ["UPDATE header SET producer = 'nobody'"]),
    ),
)
"""Every invalid file, in the order the README lists them."""

NO_FILE = {
    "inv-8": (
        "Node ids unique in a tessera: format.sql's `UNIQUE` forbids duplicates, and a file "
        "without it fails section 3.1. The checker still looks for duplicate ids "
        "(`GROUP BY id HAVING count(*) > 1`)."
    ),
    "inv-9": (
        "A rule-based tessera is deterministic: one file cannot show it. The tessera builders "
        "test it (two builds give the same knowledge hash); the checker skips it."
    ),
}
"""Invariants without a file (decisions on #9, Q1 and Q2), and why."""

README_HEAD = """\
# Invalid files

One invalid tessera or mosaic per invariant of section 3.9 of the specification (section 11),
and one per further rule the checker reports (issue #9). A checker must reject each file naming
the rules in `cases.json`, and no other. Files are named `inv-<n>-<slug>` after the invariant
they break (Part 2, invariants 1 to 15), or after the rule.

Generated by `scripts/make_invalid_files.py`: each starts from a conforming file and breaks one
rule. Some rules cannot be broken without also breaking a CHECK or foreign key of `format.sql`;
those files name `constraint` (section 3.1) too, as the table shows. `{piece}` is the
conforming tessera, a piece of `inv-15-notice.mosaic`, which is checked with it.

| File | Names | Broken by |
| --- | --- | --- |
"""


def readme() -> str:
    lines = [README_HEAD.format(piece=PIECE)]
    for case in CASES:
        names = ", ".join(f"`{rule}`" for rule in case.rules)
        lines.append(f"| `{case.name}` | {names} | {case.broken_by} |\n")
    lines.append("\nInvariants without a file:\n\n")
    for rule, why in NO_FILE.items():
        lines.append(f"- `{rule}`: {why}\n")
    lines.append(
        "\nUniqueness of `(type, key)` in a mosaic (invariant 10) has no file for the same "
        "reason as invariant 8.\n"
    )
    return "".join(lines)


def cases_json() -> str:
    data = {c.name: {"rules": list(c.rules), "pieces": list(c.pieces)} for c in CASES}
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def outputs() -> list[str]:
    """The names of every file the script writes."""
    return [PIECE, *(c.name for c in CASES), "cases.json", "README.md"]


def write(out: Path) -> None:
    """Write every file into ``out``, replacing only the files this script writes."""
    out.mkdir(parents=True, exist_ok=True)
    for name in outputs():
        (out / name).unlink(missing_ok=True)
    piece_hash = seal(out / PIECE, tessera()).knowledge_hash
    for case in CASES:
        case.make(out / case.name, piece_hash)
    (out / "cases.json").write_text(cases_json(), "utf-8", newline="\n")
    (out / "README.md").write_text(readme(), "utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help=f"directory (default {OUT})")
    args = parser.parse_args(argv)
    write(args.out)
    print(f"wrote {len(CASES) + 1} files, cases.json and README.md to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
