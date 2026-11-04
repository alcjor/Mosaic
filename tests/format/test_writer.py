"""``mosaic_format.writer`` writes content sealed (Spec 0.1 sections 3.6 and 7.1 step 8).

- Builders give content with text ids only; the writer ranks it: row ids are dense (1 to n)
  and follow the canonical order of section 3.6, text ordered by its UTF-8 bytes.
- Sealing writes the derived tables (``link_count`` for a mosaic, ``search`` for both),
  computes both hashes, writes the header and runs ``ANALYZE`` and ``VACUUM``.
- The same content in any input order, in any process, gives the same knowledge hash.
"""

import dataclasses
import json
import os
import random
import sqlite3
import subprocess
import sys
import typing
from collections.abc import Sequence
from pathlib import Path

import pytest
from mosaic_format import APPLICATION_ID, USER_VERSION, create, knowledge_hash, vector_hash
from mosaic_format.canonical_json import canonical_json
from mosaic_format.hashes import knowledge_hash_sql
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
    seal,
)

from tests.conftest import REPO

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_P = "0123456789abcdef" * 4
SIDECARS = ("-journal", "-wal", "-shm")

# Keys chosen so that UTF-8 byte order differs from case-insensitive or locale order:
# upper case sorts before lower case, and non-ASCII after both.
KEYS = ["b", "B", "a", "A", "é", "Z", "z9", "x-7", "x_7", "x.7", "10", "9", "ä", "Ω", "a'b"]


def sample(kind: str, seed: int = 7) -> Content:
    """A small graph exercising every table, built deterministically from ``seed``."""
    rnd = random.Random(seed)
    mosaic = kind == "mosaic"
    sources = [
        Source(id="src:one", kind="file", hash=HASH_A, path="one.csv", notice="It's open"),
    ]
    if mosaic:
        sources.append(
            Source(id="src:Two", kind="tessera", hash=HASH_B, path=None, notice=None, text="T2")
        )
    else:
        sources[0] = dataclasses.replace(sources[0], text="whole text of one")
    sids = [s.id for s in sources]
    types = [
        Type(name="Thing", kind="node", key_prop="code", props='{"code":"text"}'),
        Type(name="Group", kind="node", description="A group"),
        Type(name="in_group", kind="edge", from_type="Thing", to_type="Group"),
        Type(name="near", kind="edge", from_type="Thing", to_type="Thing"),
    ]
    things = [
        Node(
            id=f"Thing:{k}",
            type="Thing",
            key=k,
            label=f"Label {k}",
            summary=None if i % 3 else f"About {k}",
            props=json.dumps({"code": k}),
        )
        for i, k in enumerate(KEYS)
    ]
    groups = [Node(id=f"Group:{k}", type="Group", key=k, label=k) for k in ("g2", "g1", "G1")]
    nodes = things + groups
    edges: list[Edge] = []
    for i, t in enumerate(things):
        edges.append(Edge(type="in_group", src=t.id, dst=groups[i % 3].id))
        if i % 2:
            edges.append(Edge(type="near", src=t.id, dst=things[(i * 5) % len(things)].id))
    # Two edges of the same type joining the same pair, told apart by the qualifier.
    edges.append(Edge(type="near", src=things[0].id, dst=things[1].id, qualifier="second"))
    edges.append(Edge(type="near", src=things[0].id, dst=things[1].id, qualifier="First"))
    edges = list({e.key: e for e in edges}.values())
    aliases = [
        Alias(text="same", node=things[0].id, origin="source"),
        Alias(text="SAME", node=things[1].id, origin="pattern"),
        Alias(text="Émile", node=things[2].id, origin="proposal"),
        Alias(text="other-name", node=groups[0].id, origin="source"),
    ]
    evidence: list[Evidence] = []
    for i, n in enumerate(nodes):
        sid = sids[i % len(sids)]
        evidence.append(
            Evidence(
                subject=n.id,
                source=sid,
                locator=f"row={i + 1}",
                method="extracted",
                producer="sample/1",
                snippet=f"passage {i} snip{n.key}",
            )
        )
        if i % 4 == 0:
            # Rows sharing subject, source and locator: ranked by the rest of the row (#41).
            same = Evidence(
                subject=n.id, source=sid, locator=f"row={i + 1}", method="extracted", producer="a/1"
            )
            evidence.append(dataclasses.replace(same, prop="code"))
            evidence.append(dataclasses.replace(same, producer="sample/0"))
            evidence.append(dataclasses.replace(same, method="inferred", confidence=0.75))
            evidence.append(dataclasses.replace(same, method="inferred", confidence=0.25))
            if mosaic:
                evidence.append(dataclasses.replace(same, via=json.dumps([HASH_B])))
                evidence.append(dataclasses.replace(same, via=json.dumps([HASH_A, HASH_B])))
            evidence.append(
                Evidence(
                    subject=n.id,
                    source=sids[0],
                    locator=f"row={i + 1};field=code",
                    method="inferred",
                    producer="sample/1",
                    prop="code",
                    confidence=rnd.choice([0.5, 1 / 3, 0.9999995, 1.0, 0.0]),
                    via=json.dumps([HASH_B]) if mosaic else None,
                )
            )
    for i, e in enumerate(edges):
        evidence.append(
            Evidence(
                subject=e.key,
                source=sids[-1],
                locator=f"line={len(edges) - i}",
                method="extracted",
                producer="sample/1",
            )
        )
        if i % 5 == 0:
            evidence.append(
                Evidence(
                    subject=e.key,
                    source=sids[0],
                    # In a mosaic the two rows differ only by source: the tie of section 3.6.
                    locator=f"line={len(edges) - i}" + ("" if mosaic else ";field=x"),
                    method="extracted",
                    producer="sample/2",
                )
            )
    mentions = (
        []
        if mosaic
        else [
            Mention(
                text=f"name{i}",
                locator=f"row={i};chars={i}-{i + 4}",
                node=things[i % 4].id,
                role="ctx.arg0",
                kind="identifier" if i % 2 else "phrase",
            )
            for i in range(9)
        ]
    )
    refs = [
        ExternalRef(
            node=things[i % 3].id,
            system="store" if i % 2 else "archive",
            kind="record",
            locator=json.dumps({"k": KEYS[i]}),
            source=sids[0],
        )
        for i in range(6)
    ]
    vectors = (
        [Vector(node=n.id, bits=bytes(rnd.randrange(256) for _ in range(48))) for n in nodes]
        if mosaic
        else []
    )
    header = (
        Header(
            kind="mosaic",
            producer="sample/1",
            settings='{"text":"full"}',
            pattern_hash=HASH_P,
            target="all",
            embed_model=f"model@{HASH_A}",
        )
        if mosaic
        else Header(kind="tessera", producer="sample/1")
    )
    return Content(
        header=header,
        sources=sources,
        types=types,
        nodes=nodes,
        edges=edges,
        aliases=aliases,
        evidence=evidence,
        mentions=mentions,
        external_refs=refs,
        vectors=vectors,
    )


def shuffled(content: Content, rnd: random.Random) -> Content:
    def mix[T](items: Sequence[T]) -> list[T]:
        out = list(items)
        rnd.shuffle(out)
        return out

    return dataclasses.replace(
        content,
        sources=mix(content.sources),
        types=mix(content.types),
        nodes=mix(content.nodes),
        edges=mix(content.edges),
        aliases=mix(content.aliases),
        evidence=mix(content.evidence),
        mentions=mix(content.mentions),
        external_refs=mix(content.external_refs),
        vectors=mix(content.vectors),
    )


def _open(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _header(con: sqlite3.Connection) -> dict[str, object]:
    cur = con.execute("SELECT * FROM header")
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row, strict=True))


@pytest.fixture(params=["tessera", "mosaic"])
def kind(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def written(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / f"sample.{kind}"
    seal(path, sample(kind))
    return path


# ---------------------------------------------------------------------------
# Done when: input order and process do not change the knowledge hash.
# ---------------------------------------------------------------------------


def test_shuffling_input_20_times_gives_the_same_knowledge_hash(tmp_path: Path, kind: str) -> None:
    content = sample(kind)
    first = seal(tmp_path / "first", content)
    rnd = random.Random(2026)
    for i in range(20):
        result = seal(tmp_path / f"shuffled-{i}", shuffled(content, rnd))
        assert result.knowledge_hash == first.knowledge_hash, f"shuffle {i}"
        assert result.vector_hash == first.vector_hash, f"shuffle {i}"


def test_shuffled_input_gives_the_same_file_bytes(tmp_path: Path, kind: str) -> None:
    """Same SQLite, same content: sealing inserts in a fixed order, so the bytes match too."""
    content = sample(kind)
    a = seal(tmp_path / "a", content).path.read_bytes()
    b = seal(tmp_path / "b", shuffled(content, random.Random(1))).path.read_bytes()
    assert a == b


_CHILD = """
import random, sys
from mosaic_format.writer import seal
from tests.format.test_writer import sample, shuffled
content = shuffled(sample(sys.argv[2]), random.Random(int(sys.argv[3])))
result = seal(sys.argv[1], content)
print(result.knowledge_hash, result.vector_hash)
"""


def test_two_processes_writing_the_same_content_give_the_same_hash(
    tmp_path: Path, kind: str
) -> None:
    outputs = []
    for n, seed in enumerate(("0", "4242")):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(
            [sys.executable, "-c", _CHILD, str(tmp_path / f"p{n}"), kind, str(n + 3)],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        outputs.append(done.stdout.split())
    assert outputs[0] == outputs[1]
    assert len(outputs[0][0]) == 64
    with _open(tmp_path / "p0") as con:
        assert outputs[0][0] == knowledge_hash(con)


# ---------------------------------------------------------------------------
# Section 3.6: dense row ids that follow content order.
# ---------------------------------------------------------------------------

# Each row id must equal the rank of its row under the order of section 3.6, which SQLite
# computes here independently with BINARY collation (UTF-8 byte order).
RANKS = {
    "source": ("sid", "id"),
    "node": ("nid", "id"),
    "edge": ("eid", "src, type, dst, qualifier"),
    # Ties of (subject, sid, locator) go by the rest of the row, NULL first, confidence by its
    # hashed value (decision on #41).
    "evidence": (
        "evid",
        "eid IS NOT NULL, coalesce(nid, eid), sid, locator, prop, method, producer, "
        "CAST(round(confidence*1000000) AS INTEGER), via",
    ),
    "mention": ("mid", "nid, locator"),
    "external_ref": ("xid", "nid, system, kind, locator"),
}


@pytest.mark.parametrize("table", sorted(RANKS))
def test_row_ids_are_dense_and_follow_canonical_order(written: Path, table: str) -> None:
    rowid, order = RANKS[table]
    with _open(written) as con:
        rows = con.execute(
            f"SELECT {rowid}, row_number() OVER (ORDER BY {order} COLLATE BINARY) FROM {table}"
        ).fetchall()
    if table == "mention" and "mosaic" in written.name:
        assert rows == []
        return
    assert rows, f"{table} is empty"
    assert sorted(r[0] for r in rows) == list(range(1, len(rows) + 1))
    assert all(r[0] == r[1] for r in rows), rows


def test_node_ids_rank_by_utf8_bytes(written: Path) -> None:
    with _open(written) as con:
        ids = [r[0] for r in con.execute("SELECT id FROM node ORDER BY nid")]
    assert ids == sorted(ids, key=lambda s: s.encode("utf-8"))
    assert ids.index("Thing:B") < ids.index("Thing:a") < ids.index("Thing:é")


def test_content_round_trips_through_the_views(written: Path, kind: str) -> None:
    content = sample(kind)
    with _open(written) as con:
        edges = set(con.execute("SELECT src, type, dst, qualifier FROM v_edge"))
        aliases = set(con.execute("SELECT text, node, origin FROM v_alias"))
        snippets = {
            r[0] for r in con.execute("SELECT snippet FROM v_evidence WHERE snippet IS NOT NULL")
        }
        evidence = con.execute("SELECT count(*) FROM evidence").fetchone()[0]
        texts = dict(
            con.execute("SELECT s.id, t.text FROM source_text t JOIN source s USING (sid)")
        )
    assert edges == {(e.src, e.type, e.dst, e.qualifier) for e in content.edges}
    assert aliases == {(a.text, a.node, a.origin) for a in content.aliases}
    assert snippets == {e.snippet for e in content.evidence if e.snippet is not None}
    assert evidence == len(content.evidence)
    assert texts == {s.id: s.text for s in content.sources if s.text is not None}


# ---------------------------------------------------------------------------
# Section 7.1 step 8 and section 3.3: sealed file and header.
# ---------------------------------------------------------------------------


def test_header_holds_both_hashes(written: Path, kind: str) -> None:
    with _open(written) as con:
        header = _header(con)
        assert header["knowledge_hash"] == knowledge_hash(con) == knowledge_hash_sql(con)
        assert header["vector_hash"] == vector_hash(con)
    assert header["format_version"] == "0.1"
    assert header["kind"] == kind
    assert header["producer"] == "sample/1"
    if kind == "mosaic":
        assert header["vector_hash"] is not None
        assert header["pattern_hash"] == HASH_P
        assert header["target"] == "all"
        assert header["embed_model"] == f"model@{HASH_A}"
    else:
        assert header["vector_hash"] is None
        assert header["settings"] == "{}"


def test_seal_returns_the_hashes_it_wrote(tmp_path: Path, kind: str) -> None:
    result = seal(tmp_path / "out", sample(kind))
    with _open(result.path) as con:
        header = _header(con)
    assert (result.knowledge_hash, result.vector_hash) == (
        header["knowledge_hash"],
        header["vector_hash"],
    )


def test_file_is_sealed_per_section_3_1(written: Path, tmp_path: Path) -> None:
    for suffix in SIDECARS:
        assert not written.with_name(written.name + suffix).exists()
    reference = sqlite3.connect(create(tmp_path / "empty", "tessera"))
    with reference:
        expected = reference.execute("SELECT type, name, sql FROM sqlite_schema ORDER BY name")
        expected = expected.fetchall()
    reference.close()
    with _open(written) as con:
        objects = con.execute(
            "SELECT type, name, sql FROM sqlite_schema WHERE name <> 'sqlite_stat1' ORDER BY name"
        ).fetchall()
        assert objects == expected
        assert con.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert con.execute("PRAGMA user_version").fetchone()[0] == USER_VERSION
        assert con.execute("PRAGMA page_size").fetchone()[0] == 4096
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_analyze_and_vacuum_ran(written: Path) -> None:
    with _open(written) as con:
        stats = con.execute("SELECT count(*) FROM sqlite_stat1").fetchone()[0]
        assert stats > 0, "ANALYZE leaves sqlite_stat1"
        assert con.execute("PRAGMA freelist_count").fetchone()[0] == 0, "VACUUM leaves no free page"


# ---------------------------------------------------------------------------
# Derived tables: link_count (mosaic only) and search (both profiles).
# ---------------------------------------------------------------------------


def test_link_counts_equal_the_edges_they_count(written: Path, kind: str) -> None:
    with _open(written) as con:
        stored = set(con.execute("SELECT nid, type, direction, count FROM link_count"))
        counted = set(
            con.execute(
                "SELECT src, type, 'out', count(*) FROM edge GROUP BY src, type "
                "UNION ALL SELECT dst, type, 'in', count(*) FROM edge GROUP BY dst, type"
            )
        )
    if kind == "mosaic":
        assert stored == counted
    else:
        assert stored == set(), "a tessera has no link counts (section 4.1)"


def test_search_has_one_row_per_node(written: Path) -> None:
    with _open(written) as con:
        nids = [r[0] for r in con.execute("SELECT nid FROM node ORDER BY nid")]
        indexed = [r[0] for r in con.execute("SELECT id FROM search_docsize ORDER BY id")]
    assert indexed == nids


@pytest.mark.parametrize(
    ("query", "node"),
    [
        ('label:"Label x-7"', "Thing:x-7"),
        ('aliases:"other-name"', "Group:g2"),
        ('summary:"About z9"', "Thing:z9"),
        ('snippets:"snipx_7"', "Thing:x_7"),
        ('"x.7"', "Thing:x.7"),
    ],
)
def test_search_indexes_label_aliases_summary_and_snippets(
    written: Path, query: str, node: str
) -> None:
    with _open(written) as con:
        hits = [
            r[0]
            for r in con.execute(
                "SELECT n.id FROM search JOIN node AS n ON n.nid = search.rowid "
                "WHERE search MATCH ?",
                (query,),
            )
        ]
    assert hits == [node]


def test_search_finds_every_alias_of_a_node(written: Path, kind: str) -> None:
    with _open(written) as con:
        hits = {
            r[0]
            for r in con.execute(
                "SELECT n.id FROM search JOIN node AS n ON n.nid = search.rowid "
                "WHERE search MATCH 'aliases:same'"
            )
        }
    # unicode61 folds case, so "same" and "SAME" are one term.
    assert hits == {a.node for a in sample(kind).aliases if a.text.lower() == "same"}
    assert hits == {"Thing:b", "Thing:B"}


def test_search_joins_aliases_in_alias_order(tmp_path: Path) -> None:
    """Section 3.6 orders aliases by text under NOCASE, so "alpha" comes before "Bravo"."""
    c = sample("tessera")
    extra = [Alias(text=t, node="Group:g1", origin="source") for t in ("Bravo", "alpha")]
    path = seal(tmp_path / "aliases", dataclasses.replace(c, aliases=[*c.aliases, *extra])).path
    query = "SELECT n.id FROM search JOIN node AS n ON n.nid = search.rowid WHERE search MATCH ?"
    with _open(path) as con:
        forward = [r[0] for r in con.execute(query, ('aliases:"alpha bravo"',))]
        backward = [r[0] for r in con.execute(query, ('aliases:"bravo alpha"',))]
    assert forward == ["Group:g1"]
    assert backward == []


_SEARCH = "SELECT n.id FROM search JOIN node AS n ON n.nid = search.rowid WHERE search MATCH ?"


def test_search_joins_snippets_in_evid_order(tmp_path: Path) -> None:
    """Section 3.2 (decision on #42): the node's snippets, in ``evid`` order."""
    c = sample("tessera")
    extra = [
        Evidence(
            subject="Group:g1",
            source=c.sources[0].id,
            locator=locator,
            method="extracted",
            producer="p/1",
            snippet=snippet,
        )
        for locator, snippet in (("row=902", "delta"), ("row=901", "charlie"))
    ]
    path = seal(tmp_path / "snippets", dataclasses.replace(c, evidence=[*c.evidence, *extra])).path
    with _open(path) as con:
        forward = [r[0] for r in con.execute(_SEARCH, ('snippets:"charlie delta"',))]
        backward = [r[0] for r in con.execute(_SEARCH, ('snippets:"delta charlie"',))]
    assert forward == ["Group:g1"]
    assert backward == []


def test_search_leaves_out_snippets_of_edge_evidence(tmp_path: Path) -> None:
    """Section 3.2 (decision on #42): only the node's own evidence is indexed."""
    c = sample("tessera")
    edge = c.edges[0]
    ev = Evidence(
        subject=edge.key,
        source=c.sources[0].id,
        locator="row=903",
        method="extracted",
        producer="p/1",
        snippet="edgeonlyword",
    )
    path = seal(tmp_path / "edge", dataclasses.replace(c, evidence=[*c.evidence, ev])).path
    with _open(path) as con:
        assert con.execute("SELECT count(*) FROM snippet WHERE text = 'edgeonlyword'").fetchone()
        assert list(con.execute(_SEARCH, ("edgeonlyword",))) == []


def test_a_phrase_can_span_two_aliases(tmp_path: Path) -> None:
    """Section 3.2 (decision on #42): the newline does not stop phrase matching; accepted."""
    c = sample("tessera")
    extra = [Alias(text=t, node="Group:g1", origin="source") for t in ("Hall One", "Park Two")]
    path = seal(tmp_path / "span", dataclasses.replace(c, aliases=[*c.aliases, *extra])).path
    with _open(path) as con:
        assert [r[0] for r in con.execute(_SEARCH, ('aliases:"one park"',))] == ["Group:g1"]


# ---------------------------------------------------------------------------
# Builders never assign row ids; the writer refuses what it cannot rank or resolve.
# ---------------------------------------------------------------------------

ROW_IDS = {"sid", "nid", "eid", "evid", "mid", "xid", "rowid"}


@pytest.mark.parametrize(
    "cls", [Source, Type, Node, Edge, Alias, Evidence, Mention, ExternalRef, Vector]
)
def test_inputs_carry_no_row_ids(cls: type[Source]) -> None:
    assert not {f.name for f in dataclasses.fields(cls)} & ROW_IDS


def test_edges_are_named_by_node_ids_not_row_ids() -> None:
    assert EdgeKey._fields == ("src", "type", "dst", "qualifier")
    assert EdgeKey("A:1", "t", "A:2") == Edge(type="t", src="A:1", dst="A:2").key


def _broken(kind: str, **changes: object) -> Content:
    return dataclasses.replace(sample(kind), **changes)


def _refused(tmp_path: Path, content: Content, *words: str) -> None:
    path = tmp_path / "refused"
    with pytest.raises(ValueError) as caught:
        seal(path, content)
    for word in words:
        assert word in str(caught.value)
    assert not path.exists(), "a failed seal leaves no file"
    for suffix in SIDECARS:
        assert not path.with_name(path.name + suffix).exists()


def test_refuses_an_edge_to_an_unknown_node(tmp_path: Path) -> None:
    c = sample("tessera")
    edges = [*c.edges, Edge(type="near", src="Thing:a", dst="Thing:nowhere")]
    _refused(tmp_path, dataclasses.replace(c, edges=edges), "Thing:nowhere", "edge")


def test_refuses_evidence_for_an_unknown_subject(tmp_path: Path) -> None:
    c = sample("tessera")
    ev = Evidence(
        subject=EdgeKey(src="Thing:a", type="near", dst="Thing:A"),
        source="src:one",
        locator="row=1",
        method="extracted",
        producer="p/1",
    )
    _refused(tmp_path, dataclasses.replace(c, evidence=[*c.evidence, ev]), "evidence", "near")


def test_refuses_evidence_from_an_unknown_source(tmp_path: Path) -> None:
    c = sample("tessera")
    ev = dataclasses.replace(c.evidence[0], source="src:missing", locator="row=99")
    _refused(tmp_path, dataclasses.replace(c, evidence=[*c.evidence, ev]), "src:missing")


def test_refuses_two_nodes_with_one_id(tmp_path: Path) -> None:
    c = sample("tessera")
    nodes = [*c.nodes, dataclasses.replace(c.nodes[0], label="other")]
    _refused(tmp_path, dataclasses.replace(c, nodes=nodes), c.nodes[0].id)


def test_refuses_two_edges_with_one_identity(tmp_path: Path) -> None:
    c = sample("tessera")
    edges = [*c.edges, dataclasses.replace(c.edges[0], props='{"x":1}')]
    _refused(tmp_path, dataclasses.replace(c, edges=edges), "edge", c.edges[0].src)


def _evidence_rows(path: Path) -> list[tuple[object, ...]]:
    with _open(path) as con:
        return con.execute(
            "SELECT evid, prop, method, producer, confidence, via FROM evidence ORDER BY evid"
        ).fetchall()


def test_orders_evidence_of_one_subject_source_and_locator_by_the_rest_of_the_row(
    tmp_path: Path,
) -> None:
    """Decision on #41: ties of (subject, sid, locator) go by (prop, method, producer,
    confidence, via), NULL before any value, text by UTF-8 bytes."""
    c = sample("mosaic")
    rows = [
        Evidence(
            subject="Thing:zz",
            source="src:one",
            locator="row=7",
            method="extracted",
            producer="table-importer/1.0",
            via=via,
        )
        for via in (json.dumps([HASH_B]), None, json.dumps([HASH_A]))
    ]
    rows.append(dataclasses.replace(rows[1], prop="code"))
    rows.append(dataclasses.replace(rows[1], producer="Table-importer/1.0"))
    rows.append(dataclasses.replace(rows[1], method="inferred", confidence=0.5))
    rows.append(dataclasses.replace(rows[1], method="inferred", confidence=0.25))
    node = Node(id="Thing:zz", type="Thing", key="zz", label="zz")
    vector = Vector(node="Thing:zz", bits=bytes(48))
    expected = [
        (None, "extracted", "Table-importer/1.0", None, None),
        (None, "extracted", "table-importer/1.0", None, None),
        (None, "extracted", "table-importer/1.0", None, json.dumps([HASH_A])),
        (None, "extracted", "table-importer/1.0", None, json.dumps([HASH_B])),
        (None, "inferred", "table-importer/1.0", 0.25, None),
        (None, "inferred", "table-importer/1.0", 0.5, None),
        ("code", "extracted", "table-importer/1.0", None, None),
    ]
    hashes = set()
    for n, order in enumerate(([*rows], [*reversed(rows)], [rows[3], *rows[:3], *rows[4:]])):
        content = dataclasses.replace(
            c,
            nodes=[*c.nodes, node],
            vectors=[*c.vectors, vector],
            evidence=[*order, *c.evidence],
        )
        result = seal(tmp_path / f"ties-{n}", content)
        hashes.add(result.knowledge_hash)
        got = [
            r[1:]
            for r in _evidence_rows(result.path)
            if r[3] in ("table-importer/1.0", "Table-importer/1.0")
        ]
        assert got == expected
    assert len(hashes) == 1


def test_keeps_the_same_citation_arriving_by_two_routes(tmp_path: Path) -> None:
    """The example on #41: one row straight from a tessera, one through mosaic M; NULL first."""
    c = sample("mosaic")
    direct = Evidence(
        subject=c.nodes[0].id,
        source="src:one",
        locator="row=7000",
        method="extracted",
        producer="table-importer/1.0",
    )
    routed = dataclasses.replace(direct, via=json.dumps([HASH_B]))
    for n, order in enumerate(([direct, routed], [routed, direct])):
        path = seal(
            tmp_path / f"routes-{n}", dataclasses.replace(c, evidence=[*order, *c.evidence])
        ).path
        with _open(path) as con:
            vias = con.execute(
                "SELECT via FROM evidence WHERE locator = 'row=7000' ORDER BY evid"
            ).fetchall()
        assert vias == [(None,), (json.dumps([HASH_B]),)]


def test_refuses_two_evidence_rows_equal_in_every_ranked_column(tmp_path: Path) -> None:
    """Decision on #41: rows equal in (subject, prop, sid, locator, method, producer, confidence,
    via) could be swapped, so the writer refuses them and names subject, source and locator."""
    c = sample("tessera")
    ev = dataclasses.replace(c.evidence[0], snippet="another passage")
    _refused(
        tmp_path,
        dataclasses.replace(c, evidence=[*c.evidence, ev]),
        c.nodes[0].id,
        c.evidence[0].source,
        c.evidence[0].locator,
    )


def test_refuses_evidence_whose_confidence_differs_only_below_the_hashed_precision(
    tmp_path: Path,
) -> None:
    """Confidence ranks by CAST(round(confidence*1000000) AS INTEGER), the value it hashes as,
    so 0.5000001 and 0.5000002 are one value and the rows are duplicates (#41)."""
    c = sample("tessera")
    ev = Evidence(
        subject=c.nodes[0].id,
        source="src:one",
        locator="row=8000",
        method="inferred",
        producer="p/1",
        confidence=0.5000001,
    )
    twin = dataclasses.replace(ev, confidence=0.5000002)
    _refused(tmp_path, dataclasses.replace(c, evidence=[*c.evidence, ev, twin]), "row=8000")


def test_edge_evidence_ties_are_ranked_too(tmp_path: Path) -> None:
    c = sample("tessera")
    key = c.edges[0].key
    ev = Evidence(subject=key, source="src:one", locator="x=1", method="extracted", producer="b/1")
    other = dataclasses.replace(ev, producer="a/1")
    hashes = {
        seal(tmp_path / f"e{n}", dataclasses.replace(c, evidence=[*o, *c.evidence])).knowledge_hash
        for n, o in enumerate(([ev, other], [other, ev]))
    }
    assert len(hashes) == 1


def test_refuses_an_alias_clash_under_nocase(tmp_path: Path) -> None:
    c = sample("tessera")
    aliases = [*c.aliases, Alias(text="Same", node=c.aliases[0].node, origin="source")]
    _refused(tmp_path, dataclasses.replace(c, aliases=aliases), "alias", c.aliases[0].node)


def test_refuses_a_check_constraint_naming_the_row(tmp_path: Path) -> None:
    c = sample("tessera")
    ev = dataclasses.replace(c.evidence[0], locator="row=500", confidence=0.5)
    _refused(tmp_path, dataclasses.replace(c, evidence=[*c.evidence, ev]), "evidence", "row=500")


def test_refuses_mentions_in_a_mosaic(tmp_path: Path) -> None:
    m = Mention(text="n", locator="row=1", node="Thing:a", role="ctx.arg0", kind="phrase")
    _refused(tmp_path, _broken("mosaic", mentions=[m]), "mention", "tessera")


def test_refuses_vectors_in_a_tessera(tmp_path: Path) -> None:
    v = Vector(node="Thing:a", bits=bytes(48))
    _refused(tmp_path, _broken("tessera", vectors=[v]), "vector", "mosaic")


def test_refuses_vectors_without_one_per_node(tmp_path: Path) -> None:
    c = sample("mosaic")
    _refused(tmp_path, dataclasses.replace(c, vectors=c.vectors[1:]), "vector", "node")


def test_refuses_vectors_without_an_embedding_model(tmp_path: Path) -> None:
    c = sample("mosaic")
    header = dataclasses.replace(c.header, embed_model=None)
    _refused(tmp_path, dataclasses.replace(c, header=header), "embed_model")


def test_never_overwrites_a_file(tmp_path: Path) -> None:
    path = tmp_path / "taken"
    path.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        seal(path, sample("tessera"))
    assert path.read_bytes() == b"keep me"


# Section 3.1, decision on #39: no text value contains U+0000.

_COLLECTIONS = {
    "sources": Source,
    "types": Type,
    "nodes": Node,
    "edges": Edge,
    "aliases": Alias,
    "evidence": Evidence,
    "mentions": Mention,
    "external_refs": ExternalRef,
    "vectors": Vector,
}


def _is_text(cls: type, field: str) -> bool:
    hint = typing.get_type_hints(cls)[field]
    return hint is str or str in typing.get_args(hint)


def _text_fields() -> list[tuple[str, str, str]]:
    cases = []
    for kind in ("tessera", "mosaic"):
        c = sample(kind)
        for collection, cls in [("header", Header), *_COLLECTIONS.items()]:
            if collection == "header" or getattr(c, collection):
                fields = dataclasses.fields(cls)
                cases += [(kind, collection, f.name) for f in fields if _is_text(cls, f.name)]
    return cases


@pytest.mark.parametrize(("kind", "collection", "field"), _text_fields())
def test_refuses_text_containing_u0000(
    tmp_path: Path, kind: str, collection: str, field: str
) -> None:
    c = sample(kind)
    text = "x\x00y"
    if collection == "header":
        changed = dataclasses.replace(c, header=dataclasses.replace(c.header, **{field: text}))
    else:
        items = list(getattr(c, collection))
        items[0] = dataclasses.replace(items[0], **{field: text})
        changed = dataclasses.replace(c, **{collection: items})
    _refused(tmp_path, changed, "U+0000", field)


def test_accepts_a_json_escape_of_u0000(tmp_path: Path) -> None:
    """A JSON ``\\u0000`` escape is six ASCII characters, not a NUL (section 3.1)."""
    c = sample("tessera")
    node = dataclasses.replace(c.nodes[0], props='{"note": "a\\u0000b"}')
    sealed = seal(tmp_path / "escape", dataclasses.replace(c, nodes=[node, *c.nodes[1:]]))
    with _open(sealed.path) as con:
        props = con.execute("SELECT props FROM node WHERE id = ?", (node.id,)).fetchone()[0]
    assert props == '{"note":"a\\u0000b"}'  # canonical JSON (section 3.1, #59)


def test_refuses_u0000_inside_the_edge_key_of_evidence(tmp_path: Path) -> None:
    c = sample("tessera")
    edge = c.edges[0]
    ev = Evidence(
        subject=EdgeKey(src=edge.src, type=edge.type, dst=edge.dst, qualifier="q\x00"),
        source=c.sources[0].id,
        locator="row=1",
        method="extracted",
        producer="p/1",
    )
    changed = dataclasses.replace(c, evidence=[*c.evidence, ev])
    _refused(tmp_path, changed, "U+0000", "subject", "evidence at 'row=1'")


# Section 3.1, decision on #59: JSON text is written in RFC 8785 canonical form.

JSON_COLUMNS = [
    ("header", "settings"),
    ("type", "props"),
    ("node", "props"),
    ("edge", "props"),
    ("evidence", "via"),
    ("external_ref", "locator"),
]


def test_every_json_text_in_the_file_is_canonical(written: Path) -> None:
    """The sample writes props with json.dumps (spaces after ":"), so this is not vacuous."""
    assert sample("tessera").nodes[0].props != canonical_json(
        sample("tessera").nodes[0].props or ""
    )
    with _open(written) as con:
        for table, column in JSON_COLUMNS:
            rows = con.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")
            for (value,) in rows:
                assert value == canonical_json(value), (table, column, value)
        node_props = con.execute("SELECT count(*) FROM node WHERE props IS NOT NULL").fetchone()
        assert node_props[0] > 0


def test_writes_props_in_canonical_form(tmp_path: Path) -> None:
    c = sample("tessera")
    node = dataclasses.replace(c.nodes[0], props='{ "b" : 2.50, "a" : [1, 2.0, "\\u00e9"] }')
    sealed = seal(tmp_path / "props", dataclasses.replace(c, nodes=[node, *c.nodes[1:]]))
    with _open(sealed.path) as con:
        props = con.execute("SELECT props FROM node WHERE id = ?", (node.id,)).fetchone()[0]
    assert props == '{"a":[1,2,"\u00e9"],"b":2.5}'


def test_json_spelling_does_not_change_the_knowledge_hash(tmp_path: Path, kind: str) -> None:
    c = sample(kind)

    def respell(text: str | None) -> str | None:
        if text is None:
            return None
        value = json.loads(text)
        if isinstance(value, dict):
            value = dict(reversed(list(value.items())))
        return json.dumps(value, indent=2)

    respelled = dataclasses.replace(
        c,
        header=dataclasses.replace(c.header, settings=respell(c.header.settings) or "{}"),
        types=[dataclasses.replace(t, props=respell(t.props) or "{}") for t in c.types],
        nodes=[dataclasses.replace(n, props=respell(n.props)) for n in c.nodes],
        edges=[dataclasses.replace(e, props=respell(e.props)) for e in c.edges],
        evidence=[dataclasses.replace(ev, via=respell(ev.via)) for ev in c.evidence],
        external_refs=[
            dataclasses.replace(x, locator=respell(x.locator) or "{}") for x in c.external_refs
        ],
    )
    assert respelled != c
    assert seal(tmp_path / "a", c).knowledge_hash == seal(tmp_path / "b", respelled).knowledge_hash


def test_refuses_two_routes_whose_via_differs_only_in_spelling(tmp_path: Path) -> None:
    """Equal JSON is one value, so these rows are full duplicates (sections 3.1 and 3.5)."""
    c = sample("mosaic")
    a = dataclasses.replace(c.evidence[0], locator="row=990", via=f'["{HASH_B}","{HASH_A}"]')
    b = dataclasses.replace(a, via=f'[ "{HASH_B}" , "{HASH_A}" ]')
    _refused(tmp_path, dataclasses.replace(c, evidence=[*c.evidence, a, b]), "evidence", "row=990")


@pytest.mark.parametrize(
    ("kind", "collection", "field"),
    [
        ("tessera", "header", "settings"),
        ("tessera", "types", "props"),
        ("tessera", "nodes", "props"),
        ("tessera", "edges", "props"),
        ("tessera", "external_refs", "locator"),
        ("mosaic", "evidence", "via"),
    ],
)
@pytest.mark.parametrize(
    ("bad", "words"),
    [
        ('{"id":9007199254740993}', "store it as a string"),
        ('{"a":1,"a":2}', "duplicate object key"),
        ('{"x":NaN}', "NaN"),
    ],
)
def test_refuses_json_that_is_not_i_json(
    tmp_path: Path, kind: str, collection: str, field: str, bad: str, words: str
) -> None:
    c = sample(kind)
    text = f"[{bad}]" if field == "via" else bad
    if collection == "header":
        changed = dataclasses.replace(c, header=dataclasses.replace(c.header, **{field: text}))
    else:
        items = list(getattr(c, collection))
        items[0] = dataclasses.replace(items[0], **{field: text})
        changed = dataclasses.replace(c, **{collection: items})
    _refused(tmp_path, changed, field, words, "(3.1)")


def test_writes_header_settings_in_canonical_form(tmp_path: Path) -> None:
    """The header is not in the knowledge hash, so only reading it back shows this (#62 review)."""
    c = sample("tessera")
    header = dataclasses.replace(c.header, settings='{ "b" : 1, "a" : [ 2.0 ] }')
    sealed = seal(tmp_path / "settings", dataclasses.replace(c, header=header))
    with _open(sealed.path) as con:
        settings = con.execute("SELECT settings FROM header").fetchone()[0]
    assert settings == '{"a":[2],"b":1}'
