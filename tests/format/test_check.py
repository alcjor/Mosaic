"""``mosaic_format.check.check_file``: invariants 1 to 15 and the file rules (Spec 0.1 3.9).

Section 3.9: "A checker MUST verify, for both profiles: one header row with a supported
version; declared types for every node and edge, with edges joining nodes of the declared from
and to types; edges pointing at nodes in the same file; at least one evidence row per node and
edge; confidence present exactly on inferred rows; canonical order and a matching knowledge
hash. For a mosaic additionally: node ids of the form ``<type>:<key>``; every piece in
``source`` pinned by hash; ``via`` present where evidence passed through a mosaic; link counts
equal to the edges they count; when vectors are present, one per node and a matching vector
hash; notices of every piece carried. For a tessera additionally: exactly one source, never a
mosaic; unique node ids."

Section 1: a checker "reports every violation of sections 3 to 6 in a file or pattern, and
accepts every conforming one". The rules decided on #9 (evidence duplicates, U+0000, exact
``search`` contents, format.sql constraints, a mosaic's ``source``) are tested here too.
"""

import hashlib
import importlib.util
import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
from mosaic_format import seal
from mosaic_format.check import INVARIANTS, NOT_CHECKED, RULES, Report, Violation, check_file
from mosaic_format.writer import EdgeKey, Evidence, Source, Type

from tests.conftest import REPO

FILES = REPO / "conformance" / "invalid" / "files"


def _load() -> ModuleType:
    path = REPO / "scripts" / "make_invalid_files.py"
    spec = importlib.util.spec_from_file_location("make_invalid_files", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_invalid_files"] = module
    spec.loader.exec_module(module)
    return module


mif = _load()
CASES: dict[str, dict[str, list[str]]] = json.loads((FILES / "cases.json").read_text("utf-8"))


def check(path: Path, pieces: list[Path] | None = None) -> Report:
    return check_file(path, pieces=pieces or [])


def tamper(path: Path, before: list[str], after: list[str] | None = None) -> None:
    mif.tamper(path, before, after or [])


@pytest.fixture
def tessera(tmp_path: Path) -> Path:
    path = tmp_path / "t.tessera"
    seal(path, mif.tessera())
    return path


@pytest.fixture
def piece_hash(tmp_path: Path) -> str:
    return seal(tmp_path / "piece.tessera", mif.tessera()).knowledge_hash


@pytest.fixture
def mosaic(tmp_path: Path, piece_hash: str) -> Path:
    path = tmp_path / "m.mosaic"
    seal(path, mif.mosaic(piece_hash))
    return path


def only(report: Report, *rules: str) -> list[Violation]:
    assert report.rules == set(rules), [str(v) for v in report.violations]
    return list(report.violations)


# --- the conformance files ----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_invalid_file_is_rejected_naming_exactly_its_rules(name: str) -> None:
    case = CASES[name]
    report = check(FILES / name, [FILES / p for p in case["pieces"]])
    assert not report.ok
    assert report.rules == set(case["rules"]), [str(v) for v in report.violations]
    for violation in report.violations:
        assert violation.file == str(FILES / name)
        assert violation.message
        if violation.rule.startswith("inv-"):
            assert f"[invariant {violation.rule[4:]}, section 3.9]" in str(violation)


def test_every_checked_invariant_and_rule_has_a_file() -> None:
    named = {rule for case in CASES.values() for rule in case["rules"]}
    without_file = {"inv-9", "piece-refused"}  # inv-8 has a file for its via half
    assert named == set(RULES) - without_file
    for name, case in CASES.items():
        rule = case["rules"][0]  # the rule the file breaks; `constraint` may follow
        prefix = f"inv-{rule[4:]}-" if rule.startswith("inv-") else f"{rule}."
        assert name.startswith(prefix), name
        assert name.endswith((".tessera", ".mosaic"))


def test_the_readme_lists_every_file_and_the_invariants_without_one() -> None:
    readme = (FILES / "README.md").read_text("utf-8")
    for name, case in CASES.items():
        row = next(line for line in readme.splitlines() if line.startswith(f"| `{name}` |"))
        for rule in case["rules"]:
            assert f"`{rule}`" in row
    assert "- `inv-8`:" in readme and "- `inv-9`:" in readme


def test_the_directory_holds_exactly_what_the_script_writes() -> None:
    assert sorted(p.name for p in FILES.iterdir()) == sorted(mif.outputs())


def test_the_script_regenerates_the_same_cases(tmp_path: Path) -> None:
    mif.write(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(mif.outputs())
    for name in ("cases.json", "README.md"):
        assert (tmp_path / name).read_bytes() == (FILES / name).read_bytes()
    for name, case in CASES.items():
        fresh = check(tmp_path / name, [tmp_path / p for p in case["pieces"]])
        committed = check(FILES / name, [FILES / p for p in case["pieces"]])
        assert [(v.rule, v.table, v.where, v.message) for v in fresh.violations] == [
            (v.rule, v.table, v.where, v.message) for v in committed.violations
        ]


def test_the_script_replaces_only_its_own_files(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("mine", "utf-8")
    mif.write(tmp_path)
    mif.write(tmp_path)
    assert (tmp_path / "keep.txt").read_text("utf-8") == "mine"


# --- conforming files pass --------------------------------------------------------------------


def test_a_conforming_tessera_has_no_violation(tessera: Path) -> None:
    report = check(tessera)
    assert report.ok, [str(v) for v in report.violations]
    assert any(s.startswith("inv-9:") for s in report.skipped)


def test_a_conforming_mosaic_has_no_violation_with_its_piece(tmp_path: Path, mosaic: Path) -> None:
    report = check(mosaic, [tmp_path / "piece.tessera"])
    assert report.ok, [str(v) for v in report.violations]
    assert any(s.startswith("inv-11:") for s in report.skipped)
    assert "inv-15: no piece file given for inner" in report.skipped


def test_the_committed_piece_is_a_conforming_tessera() -> None:
    assert check(FILES / mif.PIECE).ok


def test_without_its_pieces_invariant_15_is_skipped_by_name(mosaic: Path) -> None:
    report = check(mosaic)
    assert report.ok
    assert "inv-15: no piece file given for first, inner" in report.skipped


def test_invariant_9_is_never_checked() -> None:
    assert NOT_CHECKED == ("inv-9",)
    assert set(INVARIANTS) == set(range(1, 16))


def test_the_checker_never_writes_the_file(mosaic: Path) -> None:
    before = (mosaic.read_bytes(), mosaic.stat().st_mtime_ns)
    check(mosaic)
    assert (mosaic.read_bytes(), mosaic.stat().st_mtime_ns) == before
    assert sorted(p.name for p in mosaic.parent.iterdir() if p.name.startswith("m.")) == [
        "m.mosaic"
    ]


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no such file"):
        check(tmp_path / "absent.mosaic")


# --- section 3.1: container and constraints -----------------------------------------------------


def test_a_journal_beside_the_file_is_a_container_violation(tessera: Path) -> None:
    tessera.with_name(tessera.name + "-wal").write_bytes(b"")
    (violation,) = only(check(tessera), "container")
    assert "-wal" in violation.message


def test_a_wrong_user_version_stops_the_check(tessera: Path) -> None:
    tamper(tessera, ["DELETE FROM header"], ["PRAGMA user_version = 2"])
    (violation,) = only(check(tessera), "container")
    assert "user_version 2" in violation.message


def test_an_extra_table_stops_the_check(tessera: Path) -> None:
    tamper(tessera, [], ["CREATE TABLE extra (x)"])
    (violation,) = only(check(tessera), "container")
    assert "extra" in violation.message


def test_not_a_database_is_a_container_violation(tmp_path: Path) -> None:
    path = tmp_path / "junk.mosaic"
    path.write_bytes(b"not sqlite" * 500)
    only(check(path), "container")


def test_a_foreign_key_names_its_table(tessera: Path) -> None:
    tamper(tessera, ["UPDATE external_ref SET sid = 7"])
    violations = only(check(tessera), "constraint")
    assert [v.table for v in violations] == ["external_ref"]
    assert "source" in violations[0].message


# --- invariants of both profiles ----------------------------------------------------------------


def test_invariant_1_unsupported_version_is_named(tessera: Path) -> None:
    tamper(tessera, ["UPDATE header SET format_version = '0.2'"])
    violations = [v for v in check(tessera).violations if v.rule == "inv-1"]
    assert len(violations) == 1 and "'0.2'" in violations[0].message


def test_invariant_8_evidence_of_a_tessera_has_no_via(tessera: Path) -> None:
    """Section 3.9 and Part 2 invariant 8 (decision on #83): a tessera's evidence has no via."""
    hash_ = "a" * 64
    tamper(tessera, [f"UPDATE evidence SET via = '[\"{hash_}\"]' WHERE evid = 1"])
    (violation,) = only(check(tessera), "inv-8")
    assert violation.table == "evidence"
    assert "via" in violation.message


def test_invariant_2_an_edge_without_evidence(tessera: Path) -> None:
    tamper(tessera, ["DELETE FROM evidence WHERE eid IS NOT NULL"])
    (violation,) = only(check(tessera), "inv-2")
    assert violation.table == "edge" and "'Row:1'" in violation.where


@pytest.mark.parametrize("confidence", ["NULL", "1.5", "-0.1"])
def test_invariant_3_an_inferred_row_needs_a_confidence_from_0_to_1(
    tessera: Path, confidence: str
) -> None:
    tamper(tessera, [f"UPDATE evidence SET confidence = {confidence} WHERE method = 'inferred'"])
    violations = [v for v in check(tessera).violations if v.rule != "constraint"]
    assert {v.rule for v in violations} == {"inv-3"}
    assert "inferred" in violations[0].message


def test_invariant_4_a_node_of_an_undeclared_type(tessera: Path) -> None:
    tamper(tessera, ["UPDATE node SET type = 'Ghost' WHERE id = 'Row:2'"])
    report = check(tessera)
    assert report.rules == {"inv-4", "constraint"}
    assert any("'Ghost' is not declared" in v.message for v in report.violations)


def test_invariant_4_an_edge_type_used_as_a_node_type(tmp_path: Path) -> None:
    content = mif.tessera()
    types = [*content.types, Type(name="Thing", kind="node")]
    nodes = [replace(n, type="in_group") if n.id == "Row:2" else n for n in content.nodes]
    path = tmp_path / "x.tessera"
    seal(path, replace(content, types=types, nodes=nodes))
    (violation,) = only(check(path), "inv-4")
    assert "declared as an edge type" in violation.message


def test_invariant_6_evidence_ties_are_broken_by_confidence(tmp_path: Path) -> None:
    """Section 3.6: ties by (sid, locator, prop, method, producer, confidence, via) (#41)."""
    content = mif.tessera()
    inferred = next(e for e in content.evidence if e.method == "inferred")
    path = tmp_path / "x.tessera"
    seal(path, replace(content, evidence=[*content.evidence, replace(inferred, confidence=0.25)]))
    assert check(path).ok
    # Swap the two confidences: the 0.5 row now comes first, with dense ids.
    tamper(
        path,
        [
            "UPDATE evidence SET confidence = CASE confidence WHEN 0.25 THEN 0.5 ELSE 0.25 END "
            "WHERE method = 'inferred'"
        ],
    )
    violations = only(check(path), "inv-6")
    assert [v.table for v in violations] == ["evidence"]


def test_invariant_6_node_order_by_utf8_bytes(tmp_path: Path) -> None:
    path = tmp_path / "x.tessera"
    seal(path, mif.tessera())
    tamper(
        path,
        [
            "UPDATE node SET id = 'Row:9' WHERE id = 'Row:1'",
        ],
    )
    # Row:9 is now nid 1 but sorts after Row:2 (nid 2).
    report = check(path)
    assert "inv-6" in report.rules
    assert any(v.table == "node" for v in report.violations if v.rule == "inv-6")


# --- tessera --------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["tessera", "mosaic"])
def test_invariant_7_a_tessera_is_not_made_from_a_tessera_or_mosaic(
    tmp_path: Path, kind: str
) -> None:
    """Sections 3.9 and 4.1: exactly one source, never a tessera or a mosaic (ADR-003)."""
    content = mif.tessera()
    sources = [replace(s, kind=kind) for s in content.sources]
    path = tmp_path / "x.tessera"
    seal(path, replace(content, sources=sources))
    (violation,) = only(check(path), "inv-7")
    assert (
        f"kind {kind!r}" in violation.message and "never a tessera or a mosaic" in violation.message
    )


def test_invariant_8_duplicate_ids_are_found_without_the_unique_constraint() -> None:
    """Decision on #9 (Q2): the checker runs its own GROUP BY even though format.sql forbids it."""
    import mosaic_format.check as c

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE node (nid INTEGER PRIMARY KEY, id TEXT)")
    con.execute("CREATE TABLE source (sid INTEGER PRIMARY KEY, id TEXT, kind TEXT)")
    con.execute("CREATE TABLE evidence (evid INTEGER PRIMARY KEY, via TEXT)")  # no via: no inv-8
    con.execute("INSERT INTO source VALUES (1, 'doc', 'file')")
    con.executemany("INSERT INTO node VALUES (?, ?)", [(1, "Row:1"), (2, "Row:1"), (3, "Row:2")])
    checker = c._Checker(Path("x.tessera"), con)
    checker.tessera()
    assert [(v.rule, v.where) for v in checker.violations] == [("inv-8", "'Row:1'")]


def test_a_tessera_alias_has_origin_source(tessera: Path) -> None:
    tamper(tessera, ["UPDATE alias SET origin = 'pattern'"])
    (violation,) = only(check(tessera), "profile")
    assert violation.table == "alias"


# --- mosaic ---------------------------------------------------------------------------------


def test_invariant_10_every_node_type_has_a_key_property(mosaic: Path) -> None:
    tamper(mosaic, ["UPDATE type SET key_prop = NULL WHERE name = 'Group'"])
    (violation,) = only(check(mosaic), "inv-10")
    assert violation.table == "type" and violation.where == "'Group'"


def test_invariant_12_via_is_null_without_mosaic_pieces(tmp_path: Path, piece_hash: str) -> None:
    content = mif.mosaic(piece_hash)
    sources = [s for s in content.sources if not s.id.startswith("inner")]
    evidence = [
        replace(e, source="first/doc") if e.source.startswith("inner") else e
        for e in content.evidence
    ]
    path = tmp_path / "x.mosaic"
    seal(path, replace(content, sources=sources, evidence=evidence))
    violations = only(check(path), "inv-12")
    assert len(violations) == 2
    assert all("no mosaic pieces" in v.message for v in violations)


def test_invariant_12_the_last_via_hash_is_a_mosaic_piece(tmp_path: Path, piece_hash: str) -> None:
    """Decision on #9 (Q5): via lists the mosaics innermost first; the last is a direct piece."""
    content = mif.mosaic(piece_hash)
    other = hashlib.sha256(b"other").hexdigest()
    inner = mif.INNER_HASH
    swapped = json.dumps([inner, other])
    good = json.dumps([other, inner])
    evidence = [
        replace(e, via=swapped)
        if isinstance(e.subject, EdgeKey) and e.via
        else replace(e, via=good)
        if e.via
        else e
        for e in content.evidence
    ]
    path = tmp_path / "x.mosaic"
    seal(path, replace(content, evidence=evidence))
    (violation,) = only(check(path), "inv-12")
    assert violation.table == "evidence" and "edge" in violation.where


def test_invariant_13_a_missing_link_count(mosaic: Path) -> None:
    tamper(
        mosaic,
        [
            "DELETE FROM link_count WHERE direction = 'out' "
            "AND nid = (SELECT nid FROM node WHERE id = 'Item:a')"
        ],
    )
    (violation,) = only(check(mosaic), "inv-13")
    assert "'Item:a'" in violation.where


def test_invariant_14_one_vector_per_node(mosaic: Path) -> None:
    tamper(mosaic, ["DELETE FROM vector WHERE nid = (SELECT nid FROM node WHERE id = 'Item:b')"])
    violations = only(check(mosaic), "inv-14")
    assert any("'Item:b'" in v.where for v in violations)


def test_invariant_14_the_model_id_names_a_file_hash(mosaic: Path) -> None:
    tamper(mosaic, [], ["UPDATE header SET embed_model = 'model@v1'"])
    (violation,) = only(check(mosaic), "inv-14")
    assert "embed_model" in violation.message


def test_invariant_15_checks_every_original_source_of_a_given_piece(
    tmp_path: Path, piece_hash: str
) -> None:
    """Decision on #9 (Q3): matched by hash and notice, cited or not; ids carry the prefix."""
    content = mif.mosaic(piece_hash)
    sources = [s for s in content.sources if s.id != "first/doc"]
    sources.append(Source(id="first/doc", kind="file", hash="1" * 64, notice=mif.DOC_NOTICE))
    path = tmp_path / "x.mosaic"
    seal(path, replace(content, sources=sources))
    (violation,) = only(check(path, [tmp_path / "piece.tessera"]), "inv-15")
    assert violation.where == "'first/doc'"


def test_a_given_piece_that_is_not_a_piece_is_skipped(tmp_path: Path, mosaic: Path) -> None:
    stranger = tmp_path / "stranger.tessera"
    content = mif.tessera()
    seal(
        stranger,
        replace(
            content,
            nodes=content.nodes[:1],
            edges=[],
            mentions=[],
            evidence=[e for e in content.evidence if e.subject == "Row:1"],
        ),
    )
    report = check(mosaic, [stranger])
    assert report.ok
    assert any("stranger.tessera is not a piece" in s for s in report.skipped)


def test_a_refused_piece_is_named(tmp_path: Path, mosaic: Path) -> None:
    piece = tmp_path / "piece.tessera"
    tamper(piece, [], ["UPDATE header SET knowledge_hash = '" + "0" * 64 + "'"])
    (violation,) = only(check(mosaic, [piece]), "piece-refused")
    assert "knowledge hash mismatch" in violation.message


# --- rules decided on #9 -----------------------------------------------------------------


def test_evidence_duplicates_compare_null_as_equal(tessera: Path) -> None:
    tamper(
        tessera,
        [
            "INSERT INTO evidence SELECT (SELECT max(evid) FROM evidence) + 1, nid, eid, prop, "
            "sid, locator, method, producer, confidence, via FROM evidence "
            "WHERE evid = (SELECT max(evid) FROM evidence)"
        ],
    )
    (violation,) = only(check(tessera), "evidence-duplicate")
    assert "2 rows" in violation.message


def test_evidence_duplicates_compare_confidence_as_hashed(tessera: Path) -> None:
    """Section 3.5: confidence compared as CAST(round(confidence*1000000) AS INTEGER)."""
    tamper(
        tessera,
        [
            "INSERT INTO evidence SELECT (SELECT max(evid) FROM evidence) + 1, nid, eid, prop, "
            "sid, locator, method, producer, 0.5000000001, via FROM evidence "
            "WHERE method = 'inferred'",
        ],
    )
    assert "evidence-duplicate" in check(tessera).rules


def test_text_nul_is_found_in_json_text_too(tessera: Path) -> None:
    tamper(tessera, ["UPDATE header SET settings = '{\"a\":\"' || char(0) || '\"}'"])
    violations = [v for v in check(tessera).violations if v.rule == "text-nul"]
    assert [(v.table, v.where) for v in violations] == [("header", "column settings")]


def test_search_aliases_in_alias_order(tmp_path: Path) -> None:
    """Section 3.2: aliases in alias order, joined by a newline."""
    from mosaic_format.writer import Alias

    content = mif.tessera()
    aliases = [*content.aliases, Alias("Zed", "Row:1", "source"), Alias("beta", "Row:1", "source")]
    path = tmp_path / "x.tessera"
    seal(path, replace(content, aliases=aliases))
    assert check(path).ok
    tamper(
        path,
        [
            "INSERT INTO search (search, rowid, label, aliases, summary, snippets) VALUES "
            "('delete', 2, 'Row one', 'beta' || char(10) || 'one' || char(10) || 'Zed', NULL, "
            "'a,1,x')",
            "INSERT INTO search (rowid, label, aliases, summary, snippets) VALUES "
            "(2, 'Row one', 'one' || char(10) || 'beta' || char(10) || 'Zed', NULL, 'a,1,x')",
        ],
    )
    (violation,) = only(check(path), "search")
    assert "'Row:1'" in violation.where and "aliases" in violation.message


def test_search_leaves_out_edge_snippets(tessera: Path) -> None:
    tamper(tessera, ["INSERT INTO snippet SELECT evid, 'edge words' FROM evidence WHERE eid = 1"])
    assert check(tessera).ok


def test_search_indexes_node_snippets(tessera: Path) -> None:
    tamper(tessera, ["UPDATE snippet SET text = 'changed words' WHERE evid = 1"])
    (violation,) = only(check(tessera), "search")
    assert "snippets" in violation.message


def test_a_mosaic_holds_no_mentions(mosaic: Path) -> None:
    tamper(mosaic, ["INSERT INTO mention VALUES (1, 'x', 'line=1', 1, 'a.b', 'identifier')"])
    (violation,) = only(check(mosaic), "profile")
    assert violation.table == "mention"


def test_type_props_kinds(tmp_path: Path) -> None:
    content = mif.tessera()
    types = [replace(t, props='{"n":3}') if t.name == "Group" else t for t in content.types]
    path = tmp_path / "x.tessera"
    seal(path, replace(content, types=types))
    (violation,) = only(check(path), "type-props")
    assert violation.where == "'Group'"


def test_violations_are_sorted_and_name_their_section(tessera: Path) -> None:
    tamper(tessera, ["DELETE FROM evidence WHERE eid IS NOT NULL"], ["PRAGMA application_id = 1"])
    (violation,) = check(tessera).violations
    assert str(violation).endswith("[container, section 3.1]")


def test_every_rule_names_its_section() -> None:
    for rule, (section, text) in RULES.items():
        assert section[0] in "3456" and text, rule


def test_extra_evidence_rows_are_allowed_when_another_column_differs(tessera: Path) -> None:
    content = mif.tessera()
    extra = Evidence("Row:2", "doc", "row=2", "extracted", "other/1")
    path = tessera.with_name("y.tessera")
    seal(path, replace(content, evidence=[*content.evidence, extra]))
    assert check(path).ok


# --- JSON text: RFC 8785 canonical form and I-JSON (section 3.1, decision on #59) --------------


@pytest.mark.parametrize(
    ("table", "column", "where", "value", "says"),
    [
        ("header", "settings", "one = 1", '{"b":1,"a":2}', "canonical form"),
        ("type", "props", "name = 'Group'", '{"k":"text","k":"json"}', "duplicate object key"),
        ("node", "props", "id = 'Row:2'", '{"n":9007199254740993}', "outside"),
        ("external_ref", "locator", "xid = 1", '{ "id" : "1" }', "canonical form"),
    ],
)
def test_json_text_is_canonical_and_i_json(
    tessera: Path, table: str, column: str, where: str, value: str, says: str
) -> None:
    tamper(tessera, [f"UPDATE {table} SET {column} = '{value}' WHERE {where}"])
    (violation,) = only(check(tessera), "canonical-json")
    assert violation.table == table and column in violation.message and says in violation.message


def test_via_is_canonical_json(mosaic: Path) -> None:
    spaced = f'[ "{mif.INNER_HASH}" ]'
    tamper(mosaic, [f"UPDATE evidence SET via = '{spaced}' WHERE eid IS NULL AND via IS NOT NULL"])
    (violation,) = only(check(mosaic), "canonical-json")
    assert violation.table == "evidence" and "'Item:b'" in violation.where


def test_a_json_escape_of_u0000_is_allowed(tmp_path: Path) -> None:
    """Section 3.1: a JSON \\u0000 escape is six ASCII characters and is allowed."""
    content = mif.tessera()
    nodes = [replace(n, props='{"a":"x\\u0000y"}') if n.id == "Row:2" else n for n in content.nodes]
    path = tmp_path / "x.tessera"
    seal(path, replace(content, nodes=nodes))
    assert check(path).ok
