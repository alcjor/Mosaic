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
from collections.abc import Sequence
from pathlib import Path

import pytest
from mosaic_format import APPLICATION_ID, USER_VERSION, create, knowledge_hash, vector_hash
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
    "evidence": ("evid", "eid IS NOT NULL, coalesce(nid, eid), sid, locator"),
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


def test_refuses_evidence_rows_section_3_6_cannot_order(tmp_path: Path) -> None:
    """Two rows of one subject with the same (source, locator) have no rank in section 3.6."""
    c = sample("tessera")
    ev = dataclasses.replace(c.evidence[0], producer="another/1")
    _refused(
        tmp_path,
        dataclasses.replace(c, evidence=[*c.evidence, ev]),
        c.evidence[0].locator,
        c.nodes[0].id,
    )


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
