"""Check a tessera or mosaic: invariants 1 to 15 (Specification 0.1, section 3.9) and more.

A checker "reports every violation of sections 3 to 6 in a file" (section 1). :func:`check_file`
reports, each naming its rule and where it is (table and text id):

- the invariants of section 3.9 (Part 2, invariants 1 to 15), as ``inv-<n>``;
- the rules decided after section 3.9 was written (issue #9): evidence rows that are full
  duplicates (section 3.5), text holding U+0000 (section 3.1), the exact contents of ``search``
  (section 3.2), JSON text in RFC 8785 canonical form and I-JSON (section 3.1, decision on #59);
- failures of ``format.sql``'s CHECK, NOT NULL and foreign-key constraints, found with
  ``PRAGMA integrity_check`` and ``PRAGMA foreign_key_check`` (``constraint``, section 3.1);
- tables a profile does not use that hold rows, and declared property kinds that are not one of
  the five of section 3.4.

Some rules need more than the file, and are listed in :attr:`Report.skipped` when not run:

- invariant 9 (a rule-based tessera is deterministic) needs a second build; the tessera
  builders test it, and no checker can from one file;
- invariant 11's "matches the pattern" needs the pattern (``mosaic check pattern.yaml``);
- invariant 15 (notices of every piece carried) needs the piece files, given as ``pieces``.

A wrong ``application_id``, ``user_version`` or schema (section 3.1) stops the check, because
the tables cannot be trusted; so does a file with no header row, which reports invariant 1 only.

Uniqueness that ``format.sql`` declares (node ids, ``(type, key)``) is checked again with
``GROUP BY … HAVING count(*) > 1``, so a file that lost the constraint still fails by name.
"""

import os
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from mosaic_format import APPLICATION_ID, FORMAT_VERSION, KINDS, USER_VERSION
from mosaic_format.canonical_json import canonical_json
from mosaic_format.file import SIDECARS
from mosaic_format.hashes import VECTOR_BYTES, knowledge_hash, vector_hash
from mosaic_format.reader import FileRefusedError, _check_schema, _reference_schema
from mosaic_format.reader import open as open_sealed

INVARIANTS: Mapping[int, str] = {
    1: "exactly one header; its format version is supported",
    2: "every node and every edge has at least one evidence row",
    3: "every inferred fact has a confidence between 0 and 1; extracted facts have none",
    4: "every node's and edge's type is declared, and edges join nodes of the declared types",
    5: "edges point to nodes in the same file",
    6: "rows are in canonical order with dense row ids, and the knowledge hash matches",
    7: "a tessera has exactly one source, which is never a tessera or a mosaic",
    8: "node ids are unique within a tessera",
    9: "a rule-based tessera is deterministic",
    10: "mosaic node ids are type plus key and unique; every node type has a key property",
    11: "every piece of a mosaic is pinned by hash",
    12: "evidence names an original source, and records the mosaics it passed through",
    13: "link counts equal the edges they count",
    14: "the vector layer, when present, has one row per node and matches its hash and model id",
    15: "notices of every piece are carried",
}
"""Invariants 1 to 15 of Part 2, which section 3.9 states normatively."""

RULES: Mapping[str, tuple[str, str]] = {
    **{f"inv-{n}": ("3.9", text) for n, text in INVARIANTS.items()},
    "container": ("3.1", "application_id, user_version and schema are those of format.sql"),
    "constraint": ("3.1", "rows satisfy format.sql's CHECK, NOT NULL and foreign keys"),
    "text-nul": ("3.1", "text values do not contain U+0000"),
    "canonical-json": ("3.1", "JSON text is in RFC 8785 canonical form and is I-JSON"),
    "search": ("3.2", "search holds exactly the expected terms of each node"),
    "profile": ("3.2", "tables a profile does not use stay empty"),
    "type-props": ("3.4", "declared properties map to text, integer, number, boolean or json"),
    "evidence-duplicate": ("3.5", "no two evidence rows are equal in every column but evid"),
    "piece-refused": ("3.8", "a given piece file breaks the reading rules"),
}
"""Every rule the checker reports, by name: the section that states it, and what it says."""

NOT_CHECKED = ("inv-9",)
"""Invariants no check of one file can show (decision on #9, Q1): always skipped."""

PIECE_KINDS = ("tessera", "mosaic")
"""Kinds of ``source`` row that are a mosaic's pieces; every other kind is an original source."""

PROP_KINDS = ("text", "integer", "number", "boolean", "json")
"""The kinds a declared property may have (section 3.4)."""

JSON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("header", "one", "settings"),
    ("type", "name", "props"),
    ("node", "nid", "props"),
    ("edge", "eid", "props"),
    ("evidence", "evid", "via"),
    ("external_ref", "xid", "locator"),
)
"""The JSON text columns (section 3.1), with the column that names their row."""

_SHOWN = 80
"""Longest canonical form quoted in a message."""

_HEX64 = re.compile(r"[0-9a-f]{64}")
_EMBED_MODEL = re.compile(r".+@[0-9a-f]{64}")


_ORDER: Mapping[str, tuple[str, str]] = {
    "source": ("sid", "id"),
    "node": ("nid", "id"),
    "edge": ("eid", "src, type, dst, qualifier"),
    "evidence": (
        "evid",
        "nid IS NULL, nid, eid, sid, locator, prop, method, producer, "
        "CAST(round(confidence*1000000) AS INTEGER), via",
    ),
    "mention": ("mid", "nid, locator"),
    "external_ref": ("xid", "nid, system, kind, locator"),
}
"""Row id and canonical order of each ranked table (section 3.6)."""


@dataclass(frozen=True, order=True)
class Violation:
    """One broken rule in one file: where it is (table, then a text id) and what is wrong."""

    file: str
    rule: str
    table: str
    where: str
    message: str

    @property
    def section(self) -> str:
        return RULES[self.rule][0]

    def __str__(self) -> str:
        place = f" {self.table}" + (f" {self.where}" if self.where else "")
        name = f"invariant {self.rule[4:]}" if self.rule.startswith("inv-") else self.rule
        return f"{self.file}:{place}: {self.message} [{name}, section {self.section}]"


@dataclass(frozen=True)
class Report:
    """What :func:`check_file` found, and the rules it could not run."""

    violations: tuple[Violation, ...]
    skipped: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def rules(self) -> frozenset[str]:
        return frozenset(v.rule for v in self.violations)


class _Stop(Exception):
    """The rest of the file cannot be trusted; report what was found so far."""


def _q(value: object) -> str:
    return repr(value)


@dataclass
class _Checker:
    path: Path
    con: sqlite3.Connection
    violations: list[Violation] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    kind: str = ""

    # --- reporting -------------------------------------------------------------------------

    def add(self, rule: str, table: str, where: str, message: str) -> None:
        self.violations.append(Violation(str(self.path), rule, table, where, message))

    def rows(self, sql: str, params: Iterable[object] = ()) -> list[tuple[object, ...]]:
        return self.con.execute(sql, tuple(params)).fetchall()

    def node_name(self, nid: object) -> str:
        found = self.rows("SELECT id FROM node WHERE nid = ?", (nid,))
        return f"node {_q(found[0][0])}" if found else f"node row {nid} (missing)"

    def edge_name(self, eid: object) -> str:
        found = self.rows(
            "SELECT s.id, e.type, d.id, e.qualifier FROM edge AS e "
            "LEFT JOIN node AS s ON s.nid = e.src LEFT JOIN node AS d ON d.nid = e.dst "
            "WHERE e.eid = ?",
            (eid,),
        )
        if not found:
            return f"edge row {eid} (missing)"
        src, type_, dst, qualifier = found[0]
        return f"edge ({_q(src)}, {_q(type_)}, {_q(dst)}, qualifier {_q(qualifier)})"

    def evidence_name(self, evid: object) -> str:
        found = self.rows(
            "SELECT v.nid, v.eid, s.id, v.locator FROM evidence AS v "
            "LEFT JOIN source AS s ON s.sid = v.sid WHERE v.evid = ?",
            (evid,),
        )
        if not found:
            return f"evidence row {evid} (missing)"
        nid, eid, source, locator = found[0]
        subject = self.node_name(nid) if nid is not None else self.edge_name(eid)
        return f"of {subject} from source {_q(source)} at {_q(locator)}"

    # --- section 3.1: container and constraints ---------------------------------------------

    def container(self) -> None:
        (application_id,) = self.con.execute("PRAGMA application_id").fetchone()
        if application_id != APPLICATION_ID:
            self.add(
                "container",
                "file",
                "",
                f"application_id 0x{application_id & 0xFFFFFFFF:08X} is not "
                f"0x{APPLICATION_ID:08X} (MOSA)",
            )
            raise _Stop
        (user_version,) = self.con.execute("PRAGMA user_version").fetchone()
        if user_version != USER_VERSION:
            self.add(
                "container",
                "file",
                "",
                f"user_version {user_version} is not {USER_VERSION} (format {FORMAT_VERSION})",
            )
            raise _Stop
        try:
            _check_schema(self.path, self.con)
        except FileRefusedError as e:
            self.add("container", "file", "", str(e).removeprefix(f"{self.path}: "))
            raise _Stop from None

    def constraints(self) -> None:
        # SQLite checks CHECK constraints in integrity_check only on a writable database, and
        # the file is never written: check an in-memory copy of it.
        copy = sqlite3.connect(":memory:")
        try:
            self.con.backup(copy)
            messages = [str(m) for (m,) in copy.execute("PRAGMA integrity_check")]
        finally:
            copy.close()
        for message in messages:
            if message != "ok":
                self.add("constraint", "file", "", f"format.sql constraint: {message}")
        for table, rowid, parent, _ in self.rows("PRAGMA foreign_key_check"):
            where = "" if rowid is None else f"row {rowid}"
            self.add(
                "constraint",
                str(table),
                where,
                f"format.sql constraint: a foreign key points at no row of {parent}",
            )

    # --- invariant 1: the header -------------------------------------------------------------

    def header(self) -> dict[str, object]:
        cursor = self.con.execute("SELECT * FROM header")
        names = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        if not rows:
            self.add("inv-1", "header", "", "the header holds no row; it must hold exactly one")
            raise _Stop
        if len(rows) > 1:
            self.add("inv-1", "header", "", f"the header holds {len(rows)} rows, not one")
        header = dict(zip(names, rows[0], strict=True))
        if header["one"] != 1:
            self.add("inv-1", "header", "", f"the header row has one = {header['one']!r}, not 1")
        if header["format_version"] != FORMAT_VERSION:
            self.add(
                "inv-1",
                "header",
                "",
                f"format version {header['format_version']!r} is not supported; "
                f"this checker reads {FORMAT_VERSION} only",
            )
        if header["kind"] not in KINDS:
            self.add("inv-1", "header", "", f"kind {header['kind']!r} is not one of {KINDS}")
            raise _Stop
        self.kind = str(header["kind"])
        return header

    # --- invariants of both profiles ---------------------------------------------------------

    def evidence_present(self) -> None:
        for (nid,) in self.rows(
            "SELECT nid FROM node WHERE nid NOT IN "
            "(SELECT nid FROM evidence WHERE nid IS NOT NULL) ORDER BY nid"
        ):
            self.add("inv-2", "node", self.node_name(nid)[5:], "the node has no evidence row")
        for (eid,) in self.rows(
            "SELECT eid FROM edge WHERE eid NOT IN "
            "(SELECT eid FROM evidence WHERE eid IS NOT NULL) ORDER BY eid"
        ):
            self.add("inv-2", "edge", self.edge_name(eid)[5:], "the edge has no evidence row")

    def confidence(self) -> None:
        for evid, method, confidence in self.rows(
            "SELECT evid, method, confidence FROM evidence WHERE "
            "(method = 'extracted' AND confidence IS NOT NULL) OR (method = 'inferred' AND "
            "(confidence IS NULL OR typeof(confidence) NOT IN ('real', 'integer') "
            "OR confidence < 0 OR confidence > 1)) "
            "OR method NOT IN ('extracted', 'inferred') ORDER BY evid"
        ):
            where = self.evidence_name(evid)
            if method == "extracted":
                message = f"an extracted row has confidence {confidence!r}; it must have none"
            elif method == "inferred":
                message = f"an inferred row has confidence {confidence!r}, not one from 0 to 1"
            else:
                message = f"method {method!r} is neither extracted nor inferred"
            self.add("inv-3", "evidence", where, message)

    def types(self) -> None:
        for nid, type_, kind in self.rows(
            "SELECT n.nid, n.type, t.kind FROM node AS n LEFT JOIN type AS t ON t.name = n.type "
            "WHERE t.kind IS NOT 'node' ORDER BY n.nid"
        ):
            what = "is not declared" if kind is None else f"is declared as an {kind} type"
            self.add("inv-4", "node", self.node_name(nid)[5:], f"type {type_!r} {what}")
        for eid, type_, kind in self.rows(
            "SELECT e.eid, e.type, t.kind FROM edge AS e LEFT JOIN type AS t ON t.name = e.type "
            "WHERE t.kind IS NOT 'edge' ORDER BY e.eid"
        ):
            what = "is not declared" if kind is None else f"is declared as a {kind} type"
            self.add("inv-4", "edge", self.edge_name(eid)[5:], f"type {type_!r} {what}")
        for name, end, ref in self.rows(
            "SELECT t.name, 'from', t.from_type FROM type AS t WHERE t.kind = 'edge' "
            "AND t.from_type NOT IN (SELECT name FROM type WHERE kind = 'node') "
            "UNION ALL SELECT t.name, 'to', t.to_type FROM type AS t WHERE t.kind = 'edge' "
            "AND t.to_type NOT IN (SELECT name FROM type WHERE kind = 'node') ORDER BY 1, 2"
        ):
            self.add("inv-4", "type", _q(name), f"its {end} type {ref!r} is not a node type")
        for eid, end, have, want in self.rows(
            "SELECT e.eid, 'source', s.type, t.from_type FROM edge AS e "
            "JOIN type AS t ON t.name = e.type AND t.kind = 'edge' "
            "JOIN node AS s ON s.nid = e.src WHERE s.type IS NOT t.from_type "
            "UNION ALL SELECT e.eid, 'target', d.type, t.to_type FROM edge AS e "
            "JOIN type AS t ON t.name = e.type AND t.kind = 'edge' "
            "JOIN node AS d ON d.nid = e.dst WHERE d.type IS NOT t.to_type ORDER BY 1, 2"
        ):
            self.add(
                "inv-4",
                "edge",
                self.edge_name(eid)[5:],
                f"its {end} node has type {have!r}; the edge type declares {want!r}",
            )

    def edge_ends(self) -> None:
        for eid, src, dst in self.rows(
            "SELECT eid, src, dst FROM edge WHERE src NOT IN (SELECT nid FROM node) "
            "OR dst NOT IN (SELECT nid FROM node) ORDER BY eid"
        ):
            ends = [
                f"{end} node row {nid}"
                for end, nid in (("source", src), ("target", dst))
                if not self.rows("SELECT 1 FROM node WHERE nid = ?", (nid,))
            ]
            self.add(
                "inv-5", "edge", f"row {eid}", f"{' and '.join(ends)} is not a node of this file"
            )

    def canonical(self, header: Mapping[str, object]) -> None:
        for table, (rowid, order) in _ORDER.items():
            # The row id breaks ties last, so rows equal in every ranked column (a duplicate,
            # reported by its own rule) do not count as out of order.
            found = self.rows(
                f"SELECT {rowid}, rank FROM (SELECT {rowid}, "
                f"row_number() OVER (ORDER BY {order}, {rowid}) AS rank FROM {table}) "
                f"WHERE {rowid} IS NOT rank ORDER BY rank LIMIT 1"
            )
            if found:
                row, rank = found[0]
                self.add(
                    "inv-6",
                    table,
                    f"row {row}",
                    f"{rowid} {row} is not {rank}, its rank in canonical order: row ids are "
                    f"dense from 1 and follow ({order})",
                )
        knowledge = knowledge_hash(self.con)
        if knowledge != header["knowledge_hash"]:
            self.add(
                "inv-6",
                "header",
                "",
                f"knowledge hash mismatch: the header says {header['knowledge_hash']!r}, "
                f"the content gives {knowledge!r}",
            )

    # --- rules decided on #9: duplicates, U+0000, search ---------------------------------------

    def evidence_duplicates(self) -> None:
        for evid, count in self.rows(
            "SELECT min(evid), count(*) FROM evidence GROUP BY nid, eid, prop, sid, locator, "
            "method, producer, CAST(round(confidence*1000000) AS INTEGER), via "
            "HAVING count(*) > 1 ORDER BY 1"
        ):
            self.add(
                "evidence-duplicate",
                "evidence",
                self.evidence_name(evid),
                f"{count} rows are equal in nid, eid, prop, sid, locator, method, producer, "
                "confidence and via; builders merge exact duplicates",
            )

    def text_nul(self) -> None:
        for table in _plain_tables():
            columns = [str(r[1]) for r in self.rows(f"PRAGMA table_info({table})")]
            for column in columns:
                test = f"typeof({column}) = 'text' AND instr(CAST({column} AS BLOB), X'00') > 0"
                count = self.rows(f"SELECT count(*) FROM {table} WHERE {test}")[0][0]
                if count:
                    self.add(
                        "text-nul",
                        table,
                        f"column {column}",
                        f"{count} text value(s) contain U+0000, which text never holds",
                    )

    def json_text(self) -> None:
        for table, key, column in JSON_COLUMNS:
            for row, value in self.rows(
                f"SELECT {key}, {column} FROM {table} WHERE typeof({column}) = 'text' "
                f"ORDER BY {key}"
            ):
                try:
                    canonical = canonical_json(str(value))
                except ValueError as e:
                    message = f"{column} is not I-JSON: {e}"
                else:
                    if canonical == value:
                        continue
                    shown = canonical if len(canonical) <= _SHOWN else canonical[:_SHOWN] + "…"
                    message = f"{column} is not in RFC 8785 canonical form, which is {shown!r}"
                self.add("canonical-json", table, self.row_name(table, row), message)

    def row_name(self, table: str, row: object) -> str:
        """How a violation names a row of a JSON column's table."""
        match table:
            case "header":
                return ""
            case "type":
                return _q(row)
            case "node":
                return self.node_name(row).removeprefix("node ")
            case "edge":
                return self.edge_name(row).removeprefix("edge ")
            case "evidence":
                return self.evidence_name(row)
            case _:
                found = self.rows(
                    "SELECT nid, system, kind FROM external_ref WHERE xid = ?", (row,)
                )
                nid, system, kind = found[0]
                return f"of {self.node_name(nid)}, system {system!r}, kind {kind!r}"

    def search(self) -> None:
        definition = next(
            sql
            for type_, name, _, sql in _reference_schema()
            if type_ == "table" and name == "search"
        )
        assert definition is not None
        expected = definition.replace(
            "CREATE VIRTUAL TABLE search", "CREATE VIRTUAL TABLE x.search", 1
        )
        con = self.con
        con.execute("ATTACH ':memory:' AS x")
        try:
            con.execute(expected)
            con.execute(
                "INSERT INTO x.search (rowid, label, aliases, summary, snippets) "
                "SELECT n.nid, n.label, "
                "(SELECT group_concat(a.text, char(10) ORDER BY a.text COLLATE NOCASE) "
                " FROM main.alias AS a WHERE a.nid = n.nid), "
                "n.summary, "
                "(SELECT group_concat(s.text, char(10) ORDER BY v.evid) FROM main.evidence AS v "
                " JOIN main.snippet AS s ON s.evid = v.evid WHERE v.nid = n.nid) "
                "FROM main.node AS n"
            )
            con.execute(
                "CREATE VIRTUAL TABLE temp.search_file USING fts5vocab(main, search, instance)"
            )
            con.execute(
                "CREATE VIRTUAL TABLE temp.search_want USING fts5vocab(x, search, instance)"
            )
            columns = "doc, col, term, offset"
            diff = self.rows(
                f"SELECT doc, col, 'not expected' FROM (SELECT {columns} FROM temp.search_file "
                f"EXCEPT SELECT {columns} FROM temp.search_want) "
                f"UNION SELECT doc, col, 'missing' FROM (SELECT {columns} FROM temp.search_want "
                f"EXCEPT SELECT {columns} FROM temp.search_file) ORDER BY 1, 2, 3"
            )
        except sqlite3.DatabaseError as e:
            self.add("search", "search", "", f"the index cannot be read ({e})")
            return
        finally:
            con.execute("DROP TABLE IF EXISTS temp.search_file")
            con.execute("DROP TABLE IF EXISTS temp.search_want")
            con.execute("DETACH x")
        by_doc: dict[object, list[str]] = {}
        for doc, col, what in diff:
            by_doc.setdefault(doc, []).append(f"{col} has terms {what}")
        for doc, problems in by_doc.items():
            self.add(
                "search",
                "search",
                f"row {doc} ({self.node_name(doc)})",
                "the index differs from the node's label, aliases, summary and snippets: "
                + "; ".join(dict.fromkeys(problems)),
            )

    # --- profiles and declared types --------------------------------------------------------

    def profile(self) -> None:
        unused = (
            {"link_count": "link counts", "vector": "vectors"}
            if self.kind == "tessera"
            else {"mention": "mentions"}
        )
        for table, what in unused.items():
            count = self.rows(f"SELECT count(*) FROM {table}")[0][0]
            if count:
                self.add(
                    "profile", table, "", f"a {self.kind} holds no {what}, but this one has {count}"
                )
        if self.kind == "tessera":
            for text, nid, origin in self.rows(
                "SELECT text, nid, origin FROM alias WHERE origin IS NOT 'source' "
                "ORDER BY nid, text"
            ):
                self.add(
                    "profile",
                    "alias",
                    f"{text!r} of {self.node_name(nid)}",
                    f"a tessera's aliases have origin 'source', not {origin!r} (section 4.1)",
                )

    def type_props(self) -> None:
        for name, prop, kind in self.rows(
            "SELECT t.name, j.key, j.value FROM type AS t, json_each(t.props) AS j "
            "WHERE json_valid(t.props) AND json_type(t.props) = 'object' "
            f"AND (j.type IS NOT 'text' OR j.value NOT IN ({', '.join('?' * len(PROP_KINDS))})) "
            "ORDER BY t.name, j.key",
            PROP_KINDS,
        ):
            self.add(
                "type-props",
                "type",
                _q(name),
                f"property {prop!r} has kind {kind!r}, not one of {', '.join(PROP_KINDS)}",
            )

    # --- tessera ------------------------------------------------------------------------------

    def tessera(self) -> None:
        sources = self.rows("SELECT id, kind FROM source ORDER BY sid")
        if len(sources) != 1:
            self.add("inv-7", "source", "", f"a tessera has exactly one source, not {len(sources)}")
        for id_, kind in sources:
            if kind in PIECE_KINDS:
                self.add(
                    "inv-7",
                    "source",
                    _q(id_),
                    f"the source has kind {kind!r}; a tessera's source is never a tessera or a "
                    "mosaic",
                )
        for id_, count in self.rows(
            "SELECT id, count(*) FROM node GROUP BY id HAVING count(*) > 1 ORDER BY id"
        ):
            self.add("inv-8", "node", _q(id_), f"{count} nodes share this id")

    # --- mosaic -------------------------------------------------------------------------------

    def mosaic(self, header: Mapping[str, object]) -> None:
        for _, id_, type_, key in self.rows(
            "SELECT nid, id, type, key FROM node WHERE id IS NOT type || ':' || key ORDER BY nid"
        ):
            self.add(
                "inv-10", "node", _q(id_), f"the id is not <type>:<key> ({type_!r}, key {key!r})"
            )
        for type_, key, count in self.rows(
            "SELECT type, key, count(*) FROM node GROUP BY type, key HAVING count(*) > 1 "
            "ORDER BY type, key"
        ):
            self.add("inv-10", "node", f"{type_}:{key}", f"{count} nodes share type and key")
        for id_, count in self.rows(
            "SELECT id, count(*) FROM node GROUP BY id HAVING count(*) > 1 ORDER BY id"
        ):
            self.add("inv-10", "node", _q(id_), f"{count} nodes share this id")
        for (name,) in self.rows(
            "SELECT name FROM type WHERE kind = 'node' AND key_prop IS NULL ORDER BY name"
        ):
            self.add("inv-10", "type", _q(name), "the node type has no key property")

        pieces = self.rows(
            "SELECT sid, id, kind, hash FROM source WHERE kind IN ('tessera', 'mosaic') "
            "ORDER BY sid"
        )
        for _, id_, _, hash_ in pieces:
            if not (isinstance(hash_, str) and _HEX64.fullmatch(hash_)):
                self.add(
                    "inv-11",
                    "source",
                    _q(id_),
                    f"the piece is not pinned by a full hash: {hash_!r} is not 64 lowercase hex",
                )
        self.skipped.append("inv-11: whether the pieces match the pattern needs the pattern")

        self.via(pieces)
        self.link_counts()
        self.vectors(header)

    def via(self, pieces: list[tuple[object, ...]]) -> None:
        mosaic_hashes = {h for _, _, kind, h in pieces if kind == "mosaic"}
        for evid, source in self.rows(
            "SELECT v.evid, s.id FROM evidence AS v JOIN source AS s ON s.sid = v.sid "
            "WHERE s.kind IN ('tessera', 'mosaic') ORDER BY v.evid"
        ):
            self.add(
                "inv-12",
                "evidence",
                self.evidence_name(evid),
                f"the row names piece {source!r} as its source; evidence names an original "
                "source, never a piece",
            )
        for evid, via in self.rows(
            "SELECT evid, via FROM evidence WHERE via IS NOT NULL ORDER BY evid"
        ):
            where = self.evidence_name(evid)
            if not mosaic_hashes:
                self.add(
                    "inv-12",
                    "evidence",
                    where,
                    f"via is {via!r}, but the file has no mosaic pieces, so via is NULL",
                )
                continue
            last = self.rows(
                "SELECT json_extract(?, '$[#-1]') WHERE json_valid(?) "
                "AND json_type(?) = 'array' AND json_array_length(?) > 0",
                (via, via, via, via),
            )
            if not last or last[0][0] not in mosaic_hashes:
                self.add(
                    "inv-12",
                    "evidence",
                    where,
                    f"via is {via!r}; its last hash must be that of a mosaic piece of this file",
                )

    def link_counts(self) -> None:
        expected = (
            "SELECT src AS nid, type, 'out' AS direction, count(*) AS count FROM edge "
            "GROUP BY src, type UNION ALL "
            "SELECT dst, type, 'in', count(*) FROM edge GROUP BY dst, type"
        )
        stored = "SELECT nid, type, direction, count FROM link_count"
        for nid, type_, direction, count, what in self.rows(
            f"SELECT *, 'stored' FROM ({stored} EXCEPT SELECT * FROM ({expected})) "
            f"UNION ALL SELECT *, 'expected' FROM ({expected} EXCEPT {stored}) ORDER BY 1, 2, 3, 5"
        ):
            message = (
                f"the {direction} count of {type_!r} edges is stored as {count}, which the edges "
                "do not give"
                if what == "stored"
                else f"the edges give an {direction} count of {count} {type_!r} edges, which "
                "link_count does not hold"
            )
            self.add("inv-13", "link_count", self.node_name(nid), message)

    def vectors(self, header: Mapping[str, object]) -> None:
        count = self.rows("SELECT count(*) FROM vector")[0][0]
        if not count and header["vector_hash"] is None and header["embed_model"] is None:
            return
        if not count:
            self.add(
                "inv-14", "header", "", "the header names a vector hash, but there are no vectors"
            )
            return
        for (nid,) in self.rows(
            "SELECT nid FROM node WHERE nid NOT IN (SELECT nid FROM vector) ORDER BY nid"
        ):
            self.add(
                "inv-14", "vector", self.node_name(nid), "the node has no vector; one per node"
            )
        for (nid,) in self.rows(
            "SELECT nid FROM vector WHERE nid NOT IN (SELECT nid FROM node) ORDER BY nid"
        ):
            self.add("inv-14", "vector", f"row {nid}", "the vector belongs to no node")
        try:
            vectors = vector_hash(self.con)
        except ValueError as e:
            self.add("inv-14", "vector", "", f"{e}; each is {VECTOR_BYTES} bytes")
        else:
            if vectors != header["vector_hash"]:
                self.add(
                    "inv-14",
                    "header",
                    "",
                    f"vector hash mismatch: the header says {header['vector_hash']!r}, the "
                    f"vectors give {vectors!r}",
                )
        model = header["embed_model"]
        if not (isinstance(model, str) and _EMBED_MODEL.fullmatch(model)):
            self.add(
                "inv-14",
                "header",
                "",
                f"embed_model {model!r} is not <name>@<SHA-256 of the model file>",
            )

    # --- invariant 15: notices of the given pieces ------------------------------------------

    def notices(self, pieces: Iterable[str | os.PathLike[str]]) -> None:
        rows = self.rows("SELECT id, hash FROM source WHERE kind IN ('tessera', 'mosaic')")
        by_hash: dict[object, str] = {h: str(i) for i, h in rows}
        carried = set(
            self.rows("SELECT hash, notice FROM source WHERE kind NOT IN ('tessera', 'mosaic')")
        )
        given = [Path(p) for p in pieces]
        checked: set[str] = set()
        for piece_path in sorted(given, key=lambda p: os.fsencode(p)):
            try:
                with open_sealed(piece_path) as piece:
                    name = by_hash.get(piece.knowledge_hash)
                    if name is None:
                        self.skipped.append(
                            f"inv-15: {piece_path} is not a piece of this file (no source row "
                            "has its knowledge hash)"
                        )
                        continue
                    originals = piece.query(
                        "SELECT id, hash, notice FROM source "
                        "WHERE kind NOT IN ('tessera', 'mosaic') ORDER BY sid"
                    )
            except (FileRefusedError, FileNotFoundError) as e:
                self.add("piece-refused", "source", str(piece_path), str(e))
                continue
            checked.add(name)
            for id_, hash_, notice in originals:
                if (hash_, notice) not in carried:
                    self.add(
                        "inv-15",
                        "source",
                        _q(f"{name}/{id_}"),
                        f"source {id_!r} of piece {name!r} (hash {hash_}, notice {notice!r}) is "
                        "not carried with the same hash and notice",
                    )
        unchecked = sorted(set(by_hash.values()) - checked)
        if unchecked:
            listed = ", ".join(unchecked)
            self.skipped.append(f"inv-15: no piece file given for {listed}")


def _plain_tables() -> list[str]:
    """The ordinary tables of ``format.sql``, without the full-text index and its shadows."""
    return sorted(
        name
        for type_, name, _, sql in _reference_schema()
        if type_ == "table"
        and sql is not None
        and not sql.startswith("CREATE VIRTUAL")
        and not name.startswith("search_")
    )


def _connect(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-only and immutable; the checker never writes to the file."""
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        con.execute("PRAGMA trusted_schema = OFF")
        con.execute("PRAGMA cell_size_check = ON")
    except BaseException:
        con.close()
        raise
    return con


def check_file(
    path: str | os.PathLike[str], *, pieces: Iterable[str | os.PathLike[str]] = ()
) -> Report:
    """Check one tessera or mosaic and return every violation found, and the rules skipped.

    ``pieces`` are the piece files available to check invariant 15; each is matched to a
    piece of the mosaic by its knowledge hash (``source.hash``). Pieces not given are not
    checked, and are listed in :attr:`Report.skipped`.
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"{target}: no such file")
    skipped = ["inv-9: a rule-based tessera's determinism is tested by its builder, not here"]
    sidecars = [s for s in SIDECARS if target.with_name(target.name + s).exists()]
    if sidecars:
        violation = Violation(
            str(target),
            "container",
            "file",
            "",
            f"{target.name}{sidecars[0]} lies beside it; a file has no journal or write-ahead log",
        )
        return Report((violation,), tuple(skipped))
    con = _connect(target)
    checker = _Checker(target, con, skipped=skipped)
    try:
        checker.container()
        checker.constraints()
        header = checker.header()
        checker.evidence_present()
        checker.confidence()
        checker.types()
        checker.edge_ends()
        checker.canonical(header)
        checker.evidence_duplicates()
        checker.text_nul()
        checker.json_text()
        checker.search()
        checker.profile()
        checker.type_props()
        if checker.kind == "tessera":
            checker.tessera()
        else:
            checker.mosaic(header)
            checker.notices(pieces)
    except _Stop:
        pass
    except sqlite3.DatabaseError as e:
        checker.add("container", "file", "", f"not a readable SQLite 3 database ({e})")
    finally:
        con.close()
    return Report(tuple(sorted(checker.violations)), tuple(checker.skipped))
