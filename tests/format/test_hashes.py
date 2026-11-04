"""Knowledge hash (Spec 0.1 section 3.6) and vector hash (section 3.7).

The expected byte strings below are written out by hand from the words of section 3.6 and
the header of ``format.sql``; they are not produced by the implementation.
"""

import hashlib
import random
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from mosaic_format import create, knowledge_hash, vector_hash
from mosaic_format.hashes import (
    KNOWLEDGE_SQL,
    encode_knowledge,
    encode_knowledge_sql,
    knowledge_hash_sql,
    quote,
    quote_confidence,
)

ZERO_HASH = "0" * 64
SOURCE_HASH = "0123456789abcdef" * 4


def python_bytes(con: sqlite3.Connection) -> bytes:
    out = bytearray()
    encode_knowledge(con, out.extend)
    return bytes(out)


def sql_bytes(con: sqlite3.Connection) -> bytes:
    out = bytearray()
    encode_knowledge_sql(con, out.extend)
    return bytes(out)


def _open(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    return con


@pytest.fixture
def empty(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    con = _open(create(tmp_path / "empty.tessera", "tessera"))
    yield con
    con.close()


# ---------------------------------------------------------------------------
# Golden file: a tiny hand-made tessera. Rows are inserted out of canonical order
# where the order is not fixed by the row id, so the encoder's ordering is tested.
# ---------------------------------------------------------------------------

GOLDEN_ROWS = [
    "INSERT INTO header (one, format_version, kind, producer, knowledge_hash) "
    f"VALUES (1, '0.1', 'tessera', 'golden/1', '{ZERO_HASH}')",
    "INSERT INTO source (sid, id, kind, path, hash, notice) "
    f"VALUES (1, 'src:a', 'file', 'a.csv', '{SOURCE_HASH}', 'It''s free')",
    "INSERT INTO type (name, kind, description, key_prop, from_type, to_type, props) "
    "VALUES ('Thing', 'node', NULL, 'code', NULL, NULL, '{\"code\":\"text\"}')",
    "INSERT INTO type (name, kind, description, key_prop, from_type, to_type, props) "
    "VALUES ('Group', 'node', 'A group', NULL, NULL, NULL, '{}')",
    "INSERT INTO type (name, kind, description, key_prop, from_type, to_type, props) "
    "VALUES ('in_group', 'edge', NULL, NULL, 'Thing', 'Group', '{}')",
    "INSERT INTO node VALUES (1, 'Group:g1', 'Group', 'g1', 'G one', NULL, NULL)",
    "INSERT INTO node VALUES "
    "(2, 'Thing:t1', 'Thing', 't1', 'O''Brien', X'00ff10', '{\"code\":\"t1\"}')",
    "INSERT INTO edge VALUES (1, 'in_group', 2, 1, '', NULL)",
    "INSERT INTO alias VALUES ('zeta', 1, 'pattern')",
    "INSERT INTO alias VALUES ('Émile', 2, 'proposal')",
    "INSERT INTO alias VALUES ('beta', 2, 'source')",
    "INSERT INTO alias VALUES ('Beta', 1, 'source')",
    "INSERT INTO alias VALUES ('alpha', 2, 'source')",
    "INSERT INTO evidence VALUES "
    "(1, 1, NULL, NULL, 1, 'file=a.csv;row=1', 'extracted', 'golden/1', NULL, NULL)",
    "INSERT INTO evidence VALUES "
    "(2, 2, NULL, 'label', 1, 'file=a.csv;row=2', 'inferred', 'golden/1', 0.0000025, NULL)",
    "INSERT INTO evidence VALUES (3, NULL, 1, NULL, 1, 'file=a.csv;row=2;field=group', "
    "'inferred', 'golden/1', 0.8, NULL)",
    "INSERT INTO snippet VALUES (2, 't1,O''Brien,g1')",
    "INSERT INTO snippet VALUES (1, 'g1,G one')",
    "INSERT INTO mention VALUES "
    "(1, 'g1', 'file=a.csv;row=2;field=group', 2, 'Thing.group', 'identifier')",
    "INSERT INTO source_text VALUES (1, 'id,name' || char(10) || 'g1,G one' || char(10))",
    "INSERT INTO external_ref VALUES (1, 2, 'files', 'document', '{\"doc\":\"t1\"}', 1)",
]

GOLDEN_BYTES = (
    "#header\n"
    "'0.1','tessera'\n"
    "#source\n"
    "1,'src:a','file','0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',"
    "'It''s free'\n"
    "#type\n"
    "'Group','node','A group',NULL,NULL,NULL,'{}'\n"
    "'Thing','node',NULL,'code',NULL,NULL,'{\"code\":\"text\"}'\n"
    "'in_group','edge',NULL,NULL,'Thing','Group','{}'\n"
    "#node\n"
    "1,'Group:g1','Group','g1','G one',NULL,NULL\n"
    "2,'Thing:t1','Thing','t1','O''Brien',X'00FF10','{\"code\":\"t1\"}'\n"
    "#edge\n"
    "1,'in_group',2,1,'',NULL\n"
    "#alias\n"
    "'alpha',2,'source'\n"
    "'Beta',1,'source'\n"
    "'beta',2,'source'\n"
    "'zeta',1,'pattern'\n"
    "'Émile',2,'proposal'\n"
    "#evidence\n"
    "1,1,NULL,NULL,1,'file=a.csv;row=1','extracted','golden/1',NULL,NULL\n"
    "2,2,NULL,'label',1,'file=a.csv;row=2','inferred','golden/1',3,NULL\n"
    "3,NULL,1,NULL,1,'file=a.csv;row=2;field=group','inferred','golden/1',800000,NULL\n"
    "#snippet\n"
    "1,'g1,G one'\n"
    "2,'t1,O''Brien,g1'\n"
    "#mention\n"
    "1,'g1','file=a.csv;row=2;field=group',2,'Thing.group','identifier'\n"
    "#source_text\n"
    "1,'id,name\n"
    "g1,G one\n"
    "'\n"
    "#external_ref\n"
    "1,2,'files','document','{\"doc\":\"t1\"}',1\n"
).encode()

EMPTY_BYTES = (
    b"#header\n#source\n#type\n#node\n#edge\n#alias\n#evidence\n"
    b"#snippet\n#mention\n#source_text\n#external_ref\n"
)


@pytest.fixture
def golden(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    con = _open(create(tmp_path / "golden.tessera", "tessera"))
    for statement in GOLDEN_ROWS:
        con.execute(statement)
    yield con
    con.close()


def test_golden_bytes_python(golden: sqlite3.Connection) -> None:
    assert python_bytes(golden) == GOLDEN_BYTES


def test_golden_bytes_sql(golden: sqlite3.Connection) -> None:
    assert sql_bytes(golden) == GOLDEN_BYTES


def test_golden_hash(golden: sqlite3.Connection) -> None:
    expected = hashlib.sha256(GOLDEN_BYTES).hexdigest()
    assert knowledge_hash(golden) == expected
    assert knowledge_hash_sql(golden) == expected
    assert len(expected) == 64 and expected == expected.lower()


def test_golden_covers_the_required_cases() -> None:
    # A text with a quote, a NULL, a blob, an inferred confidence and a non-ASCII alias.
    assert b"'O''Brien'" in GOLDEN_BYTES and b"NULL" in GOLDEN_BYTES
    assert b"X'00FF10'" in GOLDEN_BYTES and b",800000," in GOLDEN_BYTES
    assert "'Émile',2".encode() in GOLDEN_BYTES


def test_empty_file_is_the_part_headings(empty: sqlite3.Connection) -> None:
    assert python_bytes(empty) == EMPTY_BYTES
    assert sql_bytes(empty) == EMPTY_BYTES
    assert knowledge_hash(empty) == hashlib.sha256(EMPTY_BYTES).hexdigest()


def test_alias_order_is_nocase_then_nid_not_binary(golden: sqlite3.Connection) -> None:
    aliases = GOLDEN_BYTES.split(b"#alias\n")[1].split(b"#evidence\n")[0].splitlines()
    texts = [line.split(b",")[0] for line in aliases]
    assert texts == [b"'alpha'", b"'Beta'", b"'beta'", b"'zeta'", "'Émile'".encode()]
    assert texts != sorted(texts)  # BINARY order would put 'Beta' first


def test_encoder_leaves_the_text_factory_alone(golden: sqlite3.Connection) -> None:
    golden.text_factory = str
    knowledge_hash(golden)
    assert golden.text_factory is str


# ---------------------------------------------------------------------------
# quote() semantics, value by value, against SQLite itself.
# ---------------------------------------------------------------------------

QUOTE_CASES = [
    None,
    0,
    -1,
    2**63 - 1,
    -(2**63),
    "",
    "plain",
    "it's",
    "''",
    "line\nbreak\r\ttab",
    "café 中 \U0001f600",
    "\u2028",
    "a\x00b",  # quote() reads text as a C string and stops at U+0000
    b"",
    b"\x00\xff\x10\xab",
]


@pytest.mark.parametrize("value", QUOTE_CASES, ids=repr)
def test_quote_matches_sqlite(value: object) -> None:
    con = sqlite3.connect(":memory:")
    try:
        (expected,) = con.execute("SELECT CAST(quote(?) AS BLOB)", (value,)).fetchone()
    finally:
        con.close()
    assert quote(value) == expected


def test_quote_examples_from_the_spec() -> None:
    assert quote(None) == b"NULL"
    assert quote(42) == b"42"
    assert quote("it's") == b"'it''s'"
    assert quote(b"\xab\x01") == b"X'AB01'"


def test_quote_refuses_real_outside_confidence() -> None:
    with pytest.raises(ValueError, match=r"part 'node', row 3.*'label'.*REAL"):
        quote(1.5, where="part 'node', row 3 in canonical order, column 'label'")


def test_text_that_is_not_utf8_is_kept_byte_for_byte(golden: sqlite3.Connection) -> None:
    golden.execute("UPDATE node SET label = CAST(X'ff41' AS TEXT) WHERE nid = 1")
    encoded = python_bytes(golden)
    assert b",'\xffA'," in encoded
    assert encoded == sql_bytes(golden)


CONFIDENCES = [
    0.0,
    1.0,
    0.5,
    0.8,
    0.3,
    0.0000005,  # x * 1e6 == 0.5: round half away from zero gives 1, not 0
    0.0000015,
    0.0000025,
    0.0000035,
    0.1234565,
    0.4999995,
    0.9999995,
    0.9999994999,
    1e-7,
    5e-324,
    0.49999999999999994,
]


def test_confidence_matches_sqlite_round() -> None:
    rng = random.Random(6)
    values = CONFIDENCES + [rng.random() for _ in range(5000)]
    values += [rng.randrange(1_000_001) / 1e6 + 5e-7 for _ in range(5000)]
    con = sqlite3.connect(":memory:")
    try:
        for value in values:
            (expected,) = con.execute(
                "SELECT CAST(quote(CAST(round(?*1000000) AS INTEGER)) AS BLOB)", (value,)
            ).fetchone()
            assert quote_confidence(value) == expected, value
    finally:
        con.close()


def test_confidence_rounds_half_away_from_zero() -> None:
    assert quote_confidence(0.0000025) == b"3"
    assert quote_confidence(0.8) == b"800000"
    assert quote_confidence(None) == b"NULL"


def test_confidence_refuses_text() -> None:
    with pytest.raises(ValueError, match="confidence"):
        quote_confidence("high")


# ---------------------------------------------------------------------------
# Python and SQL agree on a 1,000-node random file.
# ---------------------------------------------------------------------------

ALPHABET = "abcXYZ019 '\"-_.,;=\n\téÉß中\U0001f600\u2028\x00"


def _text(rng: random.Random, low: int = 0, high: int = 12) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(low, high)))


def _maybe(rng: random.Random, value: object, p: float = 0.3) -> object:
    return None if rng.random() < p else value


def _fill_random(con: sqlite3.Connection, rng: random.Random, nodes: int = 1000) -> None:
    con.execute("BEGIN")
    con.execute(
        "INSERT INTO header (one, format_version, kind, producer, knowledge_hash) "
        f"VALUES (1, '0.1', 'tessera', 'random/1', '{ZERO_HASH}')"
    )
    con.execute(
        "INSERT INTO source (sid, id, kind, path, hash, notice) VALUES (1, ?, 'file', ?, ?, ?)",
        ("src:" + _text(rng, 1), _text(rng), SOURCE_HASH, _maybe(rng, _text(rng))),
    )
    node_types = ["A", "B", "Cz", "D9"]
    for name in rng.sample(node_types, len(node_types)):
        con.execute(
            "INSERT INTO type (name, kind, description, key_prop, props) "
            "VALUES (?, 'node', ?, ?, '{}')",
            (name, _maybe(rng, _text(rng)), _maybe(rng, "k")),
        )
    for name in ["e", "f_g"]:
        con.execute(
            "INSERT INTO type (name, kind, from_type, to_type, props) VALUES (?, 'edge', ?, ?, ?)",
            (name, rng.choice(node_types), rng.choice(node_types), '{"w":"number"}'),
        )
    ids = sorted({f"{rng.choice(node_types)}:{i}-{_text(rng, 0, 4)}" for i in range(nodes)})
    ids = sorted(ids, key=lambda s: s.encode())
    for nid, node_id in enumerate(ids, start=1):
        node_type, key = node_id.split(":", 1)
        summary = rng.choice([None, _text(rng), bytes(rng.randrange(256) for _ in range(5))])
        props = _maybe(rng, '{"k":"' + str(rng.randint(0, 9)) + '"}')
        con.execute(
            "INSERT INTO node VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nid, node_id, node_type, key, _maybe(rng, _text(rng)), summary, props),
        )
    edges = sorted(
        {
            (rng.randint(1, len(ids)), rng.choice(["e", "f_g"]), rng.randint(1, len(ids)), q)
            for q in ["", "", "x"]
            for _ in range(len(ids) // 2)
        }
    )
    for eid, (src, edge_type, dst, qualifier) in enumerate(edges, start=1):
        con.execute(
            "INSERT INTO edge VALUES (?, ?, ?, ?, ?, ?)",
            (eid, edge_type, src, dst, qualifier, _maybe(rng, '{"w":1.5}')),
        )
    for _ in range(len(ids)):
        con.execute(
            "INSERT OR IGNORE INTO alias VALUES (?, ?, ?)",
            (
                _text(rng, 1, 3).replace("\x00", ""),
                rng.randint(1, len(ids)),
                rng.choice(["source", "pattern", "proposal"]),
            ),
        )
    evid = 0
    subjects = [("nid", n) for n in range(1, len(ids) + 1)]
    subjects += [("eid", e) for e in range(1, len(edges) + 1)]
    for column, subject in subjects:
        for row in sorted(rng.sample(range(100), rng.randint(1, 2))):
            evid += 1
            inferred = rng.random() < 0.4
            confidence = rng.choice([rng.random(), 0.0000025, 1.0, 0.0]) if inferred else None
            con.execute(
                f"INSERT INTO evidence (evid, {column}, prop, sid, locator, method, producer, "
                "confidence, via) VALUES (?, ?, ?, 1, ?, ?, 'random/1', ?, ?)",
                (
                    evid,
                    subject,
                    _maybe(rng, "label", 0.7),
                    f"file=a;row={row:03d}",
                    "inferred" if inferred else "extracted",
                    confidence,
                    _maybe(rng, f'["{ZERO_HASH}"]', 0.8),
                ),
            )
            if rng.random() < 0.5:
                con.execute("INSERT INTO snippet VALUES (?, ?)", (evid, _text(rng, 0, 40)))
    for mid, nid in enumerate(sorted(rng.sample(range(1, len(ids) + 1), 200)), start=1):
        con.execute(
            "INSERT INTO mention VALUES (?, ?, ?, ?, 'A.b', ?)",
            (mid, _text(rng), f"row={mid:04d}", nid, rng.choice(["identifier", "phrase"])),
        )
    con.execute("INSERT INTO source_text VALUES (1, ?)", (_text(rng, 100, 400),))
    for xid, nid in enumerate(sorted(rng.sample(range(1, len(ids) + 1), 50)), start=1):
        con.execute(
            "INSERT INTO external_ref VALUES (?, ?, 'sys', 'record', ?, 1)",
            (xid, nid, '{"id":"' + str(nid) + '"}'),
        )
    con.execute("COMMIT")


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_python_and_sql_agree_on_a_random_file(tmp_path: Path, seed: int) -> None:
    con = _open(create(tmp_path / "random.tessera", "tessera"))
    try:
        _fill_random(con, random.Random(seed))
        assert con.execute("SELECT count(*) FROM node").fetchone()[0] == 1000
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        encoded = python_bytes(con)
        assert encoded == sql_bytes(con)
        assert len(encoded) > 50_000
        assert knowledge_hash(con) == knowledge_hash_sql(con)
        assert knowledge_hash(con) == hashlib.sha256(encoded).hexdigest()
    finally:
        con.close()


def test_knowledge_sql_states_the_confidence_and_alias_rules() -> None:
    # Wording check only; test_golden_bytes_sql is what shows the query is right.
    lowered = KNOWLEDGE_SQL.lower()
    assert "quote(cast(round(confidence*1000000) as integer))" in lowered
    assert "order by text collate nocase, nid" in lowered


# ---------------------------------------------------------------------------
# Every hashed column moves the hash; derived and informative columns do not.
# ---------------------------------------------------------------------------

# (table, column, row filter, new value), one per column of the table in section 3.6.
HASHED = [
    ("header", "format_version", "one = 1", "'0.2'"),
    ("header", "kind", "one = 1", "'mosaic'"),
    ("source", "sid", "sid = 1", "7"),
    ("source", "id", "sid = 1", "'src:b'"),
    ("source", "kind", "sid = 1", "'database'"),
    ("source", "hash", "sid = 1", f"'{'f' * 64}'"),
    ("source", "notice", "sid = 1", "NULL"),
    ("type", "name", "name = 'Group'", "'Grp'"),
    ("type", "kind", "name = 'Group'", "'edge'"),
    ("type", "description", "name = 'Group'", "'Groups'"),
    ("type", "key_prop", "name = 'Group'", "'gid'"),
    ("type", "from_type", "name = 'in_group'", "'Group'"),
    ("type", "to_type", "name = 'in_group'", "'Thing'"),
    ("type", "props", "name = 'Group'", '\'{"x":"text"}\''),
    ("node", "nid", "nid = 1", "9"),
    ("node", "id", "nid = 1", "'Group:g2'"),
    ("node", "type", "nid = 1", "'Thing'"),
    ("node", "key", "nid = 1", "'g2'"),
    ("node", "label", "nid = 1", "'G One'"),
    ("node", "summary", "nid = 1", "'about'"),
    ("node", "props", "nid = 1", "'{}'"),
    ("edge", "eid", "eid = 1", "5"),
    ("edge", "type", "eid = 1", "'other'"),
    ("edge", "src", "eid = 1", "1"),
    ("edge", "dst", "eid = 1", "2"),
    ("edge", "qualifier", "eid = 1", "'q'"),
    ("edge", "props", "eid = 1", "'{}'"),
    ("alias", "text", "text = 'zeta'", "'Zeta'"),
    ("alias", "nid", "text = 'zeta'", "2"),
    ("alias", "origin", "text = 'zeta'", "'source'"),
    ("evidence", "evid", "evid = 3", "4"),
    ("evidence", "nid", "evid = 1", "2"),
    ("evidence", "eid", "evid = 2", "1"),
    ("evidence", "prop", "evid = 1", "'label'"),
    ("evidence", "sid", "evid = 1", "2"),
    ("evidence", "locator", "evid = 1", "'file=a.csv;row=9'"),
    ("evidence", "method", "evid = 1", "'inferred'"),
    ("evidence", "producer", "evid = 1", "'golden/2'"),
    ("evidence", "confidence", "evid = 3", "0.81"),
    ("evidence", "via", "evid = 1", f"'[\"{ZERO_HASH}\"]'"),
    ("snippet", "evid", "evid = 2", "3"),
    ("snippet", "text", "evid = 1", "'g1,G One'"),
    ("mention", "mid", "mid = 1", "2"),
    ("mention", "text", "mid = 1", "'G1'"),
    ("mention", "locator", "mid = 1", "'row=2'"),
    ("mention", "nid", "mid = 1", "1"),
    ("mention", "role", "mid = 1", "'Thing.other'"),
    ("mention", "kind", "mid = 1", "'phrase'"),
    ("source_text", "sid", "sid = 1", "2"),
    ("source_text", "text", "sid = 1", "'id,name'"),
    ("external_ref", "xid", "xid = 1", "2"),
    ("external_ref", "nid", "xid = 1", "1"),
    ("external_ref", "system", "xid = 1", "'other'"),
    ("external_ref", "kind", "xid = 1", "'timeseries'"),
    ("external_ref", "locator", "xid = 1", '\'{"doc":"t2"}\''),
    ("external_ref", "sid", "xid = 1", "2"),
]


def _mutated_hashes(con: sqlite3.Connection, statements: list[str]) -> tuple[str, str]:
    """Both hashes after ``statements``, rolled back afterwards; constraints are relaxed so a
    single column can change on its own."""
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("PRAGMA ignore_check_constraints = ON")
    con.execute("BEGIN")
    try:
        for statement in statements:
            assert con.execute(statement).rowcount >= 1 or statement.startswith("INSERT"), statement
        return knowledge_hash(con), knowledge_hash_sql(con)
    finally:
        con.execute("ROLLBACK")
        con.execute("PRAGMA ignore_check_constraints = OFF")
        con.execute("PRAGMA foreign_keys = ON")


def test_hashed_columns_cover_every_part() -> None:
    expected = {
        "header": 2,
        "source": 5,
        "type": 7,
        "node": 7,
        "edge": 6,
        "alias": 3,
        "evidence": 10,
        "snippet": 2,
        "mention": 6,
        "source_text": 2,
        "external_ref": 6,
    }
    counts: dict[str, int] = {}
    for table, _, _, _ in HASHED:
        counts[table] = counts.get(table, 0) + 1
    assert counts == expected


@pytest.mark.parametrize(
    ("table", "column", "where", "value"),
    HASHED,
    ids=[f"{t}.{c}" for t, c, _, _ in HASHED],
)
def test_changing_a_hashed_column_changes_the_hash(
    golden: sqlite3.Connection, table: str, column: str, where: str, value: str
) -> None:
    before = knowledge_hash(golden)
    after, after_sql = _mutated_hashes(
        golden, [f"UPDATE {table} SET {column} = {value} WHERE {where}"]
    )
    assert after != before
    assert after == after_sql
    assert knowledge_hash(golden) == before


UNHASHED = [
    ["INSERT INTO link_count VALUES (2, 'in_group', 'out', 1)"],
    ["INSERT INTO link_count VALUES (1, 'in_group', 'in', 1)"],
    [
        "INSERT INTO search (rowid, label, aliases, summary, snippets) "
        "VALUES (1, 'G one', '', '', '')"
    ],
    ["UPDATE header SET producer = 'other/9'"],
    ['UPDATE header SET settings = \'{"text":"full"}\''],
    ["UPDATE header SET knowledge_hash = '" + "a" * 64 + "'"],
    ["UPDATE source SET path = 'moved/a.csv'"],
    ["INSERT INTO vector VALUES (1, zeroblob(48))"],
]


@pytest.mark.parametrize("statements", UNHASHED, ids=lambda s: s[0][:40])
def test_derived_and_informative_columns_do_not_change_the_hash(
    golden: sqlite3.Connection, statements: list[str]
) -> None:
    before = knowledge_hash(golden)
    assert _mutated_hashes(golden, statements) == (before, before)


def test_link_count_and_search_are_not_hashed(golden: sqlite3.Connection) -> None:
    before = knowledge_hash(golden)
    golden.execute("INSERT INTO link_count VALUES (2, 'in_group', 'out', 1)")
    golden.execute("INSERT INTO link_count VALUES (1, 'in_group', 'in', 1)")
    golden.execute(
        "INSERT INTO search (rowid, label, aliases, summary, snippets) "
        "VALUES (1, 'G one', 'Beta zeta', '', 'g1,G one')"
    )
    assert knowledge_hash(golden) == before
    assert knowledge_hash_sql(golden) == before
    assert python_bytes(golden) == GOLDEN_BYTES


# ---------------------------------------------------------------------------
# Vector hash (section 3.7).
# ---------------------------------------------------------------------------


def _bits(n: int) -> bytes:
    return bytes((n * 7 + i) % 256 for i in range(48))


def test_no_vectors_no_vector_hash(golden: sqlite3.Connection) -> None:
    assert vector_hash(golden) is None


def test_vector_hash_is_bits_in_nid_order(golden: sqlite3.Connection) -> None:
    golden.execute("INSERT INTO vector VALUES (2, ?)", (_bits(2),))
    golden.execute("INSERT INTO vector VALUES (1, ?)", (_bits(1),))
    expected = hashlib.sha256(_bits(1) + _bits(2)).hexdigest()
    assert vector_hash(golden) == expected


def test_vector_hash_binds_each_vector_to_its_node(golden: sqlite3.Connection) -> None:
    golden.execute("INSERT INTO vector VALUES (1, ?)", (_bits(1),))
    golden.execute("INSERT INTO vector VALUES (2, ?)", (_bits(2),))
    before = vector_hash(golden)
    golden.execute("UPDATE vector SET bits = ? WHERE nid = 1", (_bits(2),))
    golden.execute("UPDATE vector SET bits = ? WHERE nid = 2", (_bits(1),))
    assert vector_hash(golden) != before


def test_vector_hash_changes_with_one_bit(golden: sqlite3.Connection) -> None:
    golden.execute("INSERT INTO vector VALUES (1, ?)", (_bits(1),))
    before = vector_hash(golden)
    flipped = bytes([_bits(1)[0] ^ 0x80]) + _bits(1)[1:]
    golden.execute("UPDATE vector SET bits = ? WHERE nid = 1", (flipped,))
    assert vector_hash(golden) != before


def test_vector_hash_does_not_change_the_knowledge_hash(golden: sqlite3.Connection) -> None:
    before = knowledge_hash(golden)
    golden.execute("INSERT INTO vector VALUES (1, ?)", (_bits(1),))
    assert knowledge_hash(golden) == before


def test_vector_hash_refuses_a_short_vector_naming_the_node(golden: sqlite3.Connection) -> None:
    golden.execute("PRAGMA ignore_check_constraints = ON")
    golden.execute("INSERT INTO vector VALUES (2, zeroblob(47))")
    with pytest.raises(ValueError, match=r"'Thing:t1'.*47-byte"):
        vector_hash(golden)
