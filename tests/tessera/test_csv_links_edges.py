"""Edge cases of the CSV linked columns (plan M1.1), written from the spec's words.

Sections: 3.1 (no U+0000), 3.3 (header.settings), 3.4 (ids and keys), 3.5 (locators),
3.6 (canonical order by UTF-8 bytes), 4.1 and 4.3 (tessera content, determinism), 5.4 (the
White_Space set, here used to trim values) and the plan's "Done when" for M1.1.
"""

import json
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build import __version__
from mosaic_build.cli import main
from mosaic_build.tessera.csv import Link, Settings, build
from mosaic_build.tessera.settings import from_json, read
from mosaic_format.check import check_file

# Section 5.4: the characters with the Unicode White_Space property.
WHITE_SPACE = (
    [chr(c) for c in range(0x09, 0x0E)]
    + ["\u0020", "\u0085", "\u00a0", "\u1680"]
    + [chr(c) for c in range(0x2000, 0x200B)]
    + ["\u2028", "\u2029", "\u202f", "\u205f", "\u3000"]
)
# Characters that Python's str.strip() removes or that look blank, but are not White_Space.
NOT_WHITE_SPACE = ["\x1c", "\x1d", "\x1e", "\x1f", "\u180e", "\u200b", "\u2060", "\ufeff"]

TAGS = Settings(type="Item", key="code", links={"tags": Link("Tag", "tagged", separator=";")})


def _csv(tmp_path: Path, text: str, name: str = "items.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _build(tmp_path: Path, text: str, settings: Settings = TAGS, out: str = "t.tessera") -> Path:
    target = tmp_path / out
    build(_csv(tmp_path, text), target, settings)
    return target


def _q(path: Path, sql: str) -> list[tuple[object, ...]]:
    with mosaic_format.open(path) as f:
        return f.query(sql)


def _tags(path: Path) -> list[str]:
    return [str(k) for (k,) in _q(path, "SELECT key FROM v_node WHERE type = 'Tag' ORDER BY id")]


# --- trimming: the White_Space set of section 5.4, nothing else --------------------------------


@pytest.mark.parametrize("space", WHITE_SPACE, ids=[f"U+{ord(c):04X}" for c in WHITE_SPACE])
def test_each_white_space_character_is_trimmed_from_a_value(tmp_path: Path, space: str) -> None:
    # plan M1.1 "each value is trimmed"; White_Space as in section 5.4
    out = _build(tmp_path, f'code,tags\nA,"{space}x{space};{space}"\n')
    assert _tags(out) == ["x"]


@pytest.mark.parametrize("space", WHITE_SPACE, ids=[f"U+{ord(c):04X}" for c in WHITE_SPACE])
def test_a_value_of_one_white_space_character_makes_nothing(tmp_path: Path, space: str) -> None:
    # plan M1.1 "white-space-only value ... makes no node and no edge"
    out = _build(tmp_path, f'code,tags\nA,"x;{space};y"\nB,"{space}"\n')
    assert _tags(out) == ["x", "y"]
    assert _q(out, "SELECT count(*) FROM v_edge WHERE src = 'Item:B'") == [(0,)]


@pytest.mark.parametrize("char", NOT_WHITE_SPACE, ids=[f"U+{ord(c):04X}" for c in NOT_WHITE_SPACE])
def test_characters_outside_white_space_are_kept_in_a_value(tmp_path: Path, char: str) -> None:
    # section 5.4: neither str.isspace nor \s is the set; only White_Space is trimmed
    out = _build(tmp_path, f'code,tags\nA,"{char}x{char}"\nB,"{char}"\n')
    assert _tags(out) == sorted([f"{char}x{char}", char], key=lambda s: s.encode("utf-8"))


def test_white_space_inside_a_value_is_kept_as_written(tmp_path: Path) -> None:
    # key = the value, trimmed only (plan M1.1); collapse is a pattern step (section 5.4)
    out = _build(tmp_path, 'code,tags\nA,"Ann  Lee"\nB,"Ann Lee"\nC,"Ann\tLee"\n')
    assert _tags(out) == ["Ann\tLee", "Ann  Lee", "Ann Lee"]


def test_a_value_with_a_line_break_inside_keeps_it(tmp_path: Path) -> None:
    out = _build(tmp_path, 'code,tags\nA,"\nAnn\nLee\n;Bo"\n')
    assert _tags(out) == ["Ann\nLee", "Bo"]
    assert check_file(out).ok


# --- keys are the value, byte for byte -----------------------------------------------------


def test_values_differing_only_in_case_are_two_nodes(tmp_path: Path) -> None:
    # section 3.4: (type, key) unique; the key is the value, with no case folding
    out = _build(tmp_path, "code,tags\nA,Ann;ann;ANN\n")
    assert _tags(out) == ["ANN", "Ann", "ann"]
    assert check_file(out).ok


def test_composed_and_decomposed_forms_are_two_nodes(tmp_path: Path) -> None:
    # text compares by UTF-8 bytes (CLAUDE.md); no normalisation form is applied
    out = _build(tmp_path, "code,tags\nA,caf\u00e9;cafe\u0301\n")
    assert sorted(_tags(out)) == sorted(["caf\u00e9", "cafe\u0301"])


def test_linked_nodes_are_in_utf8_byte_order_not_utf16_order(tmp_path: Path) -> None:
    # section 3.6: node row ids follow `id` ordered by UTF-8 bytes
    values = ["\U00010000", "\ue000", "\uff5e", "a", "B", "\u00e9"]
    out = _build(tmp_path, "code,tags\nA," + ";".join(values) + "\n")
    in_row_order = [
        str(i) for (i,) in _q(out, "SELECT id FROM node WHERE type = 'Tag' ORDER BY nid")
    ]
    expected = sorted((f"Tag:{v}" for v in values), key=lambda s: s.encode("utf-8"))
    assert in_row_order == expected
    assert check_file(out).ok


def test_a_value_with_a_colon_equals_or_semicolon_in_a_quoted_cell(tmp_path: Path) -> None:
    # section 3.4: id = type:key; section 3.5: the locator names the column, not the value
    out = _build(
        tmp_path,
        "code,tags\nA,a:b|c=d\n",
        Settings(type="Item", key="code", links={"tags": Link("Tag", "tagged", separator="|")}),
    )
    assert [str(i) for (i,) in _q(out, "SELECT id FROM v_node WHERE type = 'Tag' ORDER BY id")] == [
        "Tag:a:b",
        "Tag:c=d",
    ]
    assert check_file(out).ok


# --- separators are literal text ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("separator", "cell", "expected"),
    [
        (".", "a.b", ["a", "b"]),
        ("|", "a|b", ["a", "b"]),
        ("*", "a*b", ["a", "b"]),
        ("\\", "a\\b", ["a", "b"]),
        ("||", "a||b|c", ["b|c", "a"]),
        (" / ", "a / b/c", ["a", "b/c"]),
        ("\u00b7", "a\u00b7b", ["a", "b"]),
        ("\t", "a\tb", ["a", "b"]),
    ],
)
def test_the_separator_is_literal_text(
    tmp_path: Path, separator: str, cell: str, expected: list[str]
) -> None:
    # plan M1.1 "split on a separator"; a separator is not a pattern
    settings = Settings(
        type="Item", key="code", links={"tags": Link("Tag", "tagged", separator=separator)}
    )
    out = _build(tmp_path, f'code,tags\nA,"{cell}"\n', settings)
    assert sorted(_tags(out), key=lambda s: s.encode("utf-8")) == sorted(
        expected, key=lambda s: s.encode("utf-8")
    )


def test_a_cell_of_only_separators_makes_nothing(tmp_path: Path) -> None:
    out = _build(tmp_path, 'code,tags\nA,";;;"\nB," ; ;; "\n')
    assert _tags(out) == []
    assert _q(out, "SELECT count(*) FROM edge") == [(0,)]
    assert check_file(out).ok


def test_leading_and_trailing_separators_make_no_empty_value(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\nA,;x;y;\n")
    assert _tags(out) == ["x", "y"]


def test_the_csv_delimiter_and_the_separator_can_be_different_characters(tmp_path: Path) -> None:
    settings = Settings(
        type="Item",
        key="code",
        delimiter="\t",
        links={"tags": Link("Tag", "tagged", separator=",")},
    )
    out = _build(tmp_path, "code\ttags\nA\tx,y\n", settings)
    assert _tags(out) == ["x", "y"]


def test_a_separator_does_not_split_a_column_without_one(tmp_path: Path) -> None:
    settings = Settings(
        type="Item",
        key="code",
        links={"tags": Link("Tag", "tagged"), "also": Link("Other", "has", separator=";")},
    )
    out = _build(tmp_path, "code,tags,also\nA,x;y,p;q\n", settings)
    assert _tags(out) == ["x;y"]
    others = _q(out, "SELECT key FROM v_node WHERE type = 'Other' ORDER BY id")
    assert others == [("p",), ("q",)]


# --- rows and locators -------------------------------------------------------------------------


def test_row_numbers_count_records_not_lines_or_blank_lines(tmp_path: Path) -> None:
    # section 3.5 `row`; a quoted line break does not start a row, blank lines are not rows
    text = 'code,tags\nA,x\n\n"B\nB",y\n\nC,z\n'
    out = _build(tmp_path, text)
    rows = _q(
        out,
        "SELECT n.key, e.locator FROM v_evidence e JOIN v_node n ON e.node = n.id "
        "WHERE n.type = 'Tag' ORDER BY n.key",
    )
    assert rows == [
        ("x", "file=items.csv;row=1;field=tags"),
        ("y", "file=items.csv;row=2;field=tags"),
        ("z", "file=items.csv;row=3;field=tags"),
    ]


def test_unquoted_u2028_and_next_line_in_a_cell_do_not_start_a_row(tmp_path: Path) -> None:
    text = "code,tags\nA,x\u2028y\nB,p\u0085q\nC,z\n"
    out = _build(tmp_path, text)
    assert sorted(_tags(out)) == sorted(["p\u0085q", "x\u2028y", "z"])
    assert _q(out, "SELECT count(*) FROM node WHERE type = 'Item'") == [(3,)]
    rows = _q(out, "SELECT locator FROM v_evidence WHERE node = 'Tag:z'")
    assert rows == [("file=items.csv;row=3;field=tags",)]


def test_crlf_line_ends_leave_no_carriage_return_in_the_last_column(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\r\nA,x;y\r\nB,z\r\n")
    assert _tags(out) == ["x", "y", "z"]


def test_a_file_without_a_final_line_end(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\nA,x;y")
    assert _tags(out) == ["x", "y"]


def test_a_linked_first_column_with_a_byte_order_mark(tmp_path: Path) -> None:
    settings = Settings(type="Item", links={"tags": Link("Tag", "tagged", separator=";")})
    out = _build(tmp_path, "\ufefftags,code\nx;y,A\n", settings)
    assert _tags(out) == ["x", "y"]


def test_without_a_key_column_edges_use_the_row_position_keys(tmp_path: Path) -> None:
    # the row node's key is its row position (existing rows behaviour); edges must join to it
    settings = Settings(type="Item", links={"tags": Link("Tag", "tagged", separator=";")})
    out = _build(tmp_path, "tags\nx;y\ny\n", settings)
    assert _q(out, "SELECT src, dst FROM v_edge ORDER BY src, dst") == [
        ("Item:1", "Tag:x"),
        ("Item:1", "Tag:y"),
        ("Item:2", "Tag:y"),
    ]
    assert check_file(out).ok


def test_one_value_in_one_row_is_one_node_one_edge_and_their_evidence(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\nA,x\n")
    assert _q(out, "SELECT id FROM v_node WHERE type = 'Tag'") == [("Tag:x",)]
    assert _q(out, "SELECT src, type, dst, qualifier FROM v_edge") == [
        ("Item:A", "tagged", "Tag:x", "")
    ]
    assert _q(out, "SELECT count(*) FROM evidence") == [(3,)]  # Item:A, Tag:x, the edge
    assert check_file(out).ok


def test_the_link_evidence_names_the_file_source_the_producer_and_no_confidence(
    tmp_path: Path,
) -> None:
    # sections 3.5 and 4.1: extracted, NULL confidence, no via, sid the one source
    out = _build(tmp_path, "code,tags\nA,x;y\nB,y\n")
    rows = _q(
        out,
        "SELECT DISTINCT s.id, e.method, e.producer, e.confidence, e.via "
        "FROM evidence e JOIN source s USING (sid)",
    )
    assert rows == [("items.csv", "extracted", f"mosaic-csv/{__version__}", None, None)]


def test_every_node_and_edge_has_evidence(tmp_path: Path) -> None:
    # section 3.5
    out = _build(tmp_path, "code,tags\nA,x;y;;z\nB,y; \nC,\n")
    assert _q(
        out,
        "SELECT count(*) FROM node WHERE nid NOT IN "
        "(SELECT nid FROM evidence WHERE nid IS NOT NULL)",
    ) == [(0,)]
    assert _q(
        out,
        "SELECT count(*) FROM edge WHERE eid NOT IN "
        "(SELECT eid FROM evidence WHERE eid IS NOT NULL)",
    ) == [(0,)]


def test_the_same_value_in_every_row_has_one_evidence_row_per_row(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\nA,x\nB,x\nC,x;x\n")
    assert _q(out, "SELECT locator FROM v_evidence WHERE node = 'Tag:x' ORDER BY locator") == [
        ("file=items.csv;row=1;field=tags",),
        ("file=items.csv;row=2;field=tags",),
        ("file=items.csv;row=3;field=tags",),
    ]
    assert _q(out, "SELECT count(*) FROM edge") == [(3,)]


def test_two_linked_columns_share_a_value_without_sharing_a_node(tmp_path: Path) -> None:
    settings = Settings(
        type="Item",
        key="code",
        links={"a": Link("Left", "has_left"), "b": Link("Right", "has_right")},
    )
    out = _build(tmp_path, "code,a,b\nA,v,v\n", settings)
    assert _q(out, "SELECT id FROM v_node WHERE type IN ('Left', 'Right') ORDER BY id") == [
        ("Left:v",),
        ("Right:v",),
    ]
    assert _q(out, "SELECT locator FROM v_evidence WHERE node = 'Left:v'") == [
        ("file=items.csv;row=1;field=a",)
    ]


def test_a_linked_value_equal_to_a_row_key_is_a_different_node(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\nA,A\n")
    assert _q(out, "SELECT src, dst FROM v_edge") == [("Item:A", "Tag:A")]


def test_in_direction_with_a_repeated_value_is_one_edge(tmp_path: Path) -> None:
    settings = Settings(
        type="Item", key="code", links={"tags": Link("Tag", "holds", "in", separator=";")}
    )
    out = _build(tmp_path, "code,tags\nA,x;x\n", settings)
    assert _q(out, "SELECT src, type, dst FROM v_edge") == [("Tag:x", "holds", "Item:A")]
    assert _q(out, "SELECT count(*) FROM v_evidence WHERE edge_type IS NOT NULL") == [(1,)]


def test_a_header_only_file_with_links_has_no_linked_things(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\n")
    assert _q(out, "SELECT count(*) FROM node") == [(0,)]
    assert _q(out, "SELECT count(*) FROM edge") == [(0,)]
    assert check_file(out).ok


def test_a_file_where_no_cell_has_a_value_makes_no_linked_things(tmp_path: Path) -> None:
    out = _build(tmp_path, "code,tags\nA,\nB, \n")
    assert _q(out, "SELECT count(*) FROM node WHERE type = 'Tag'") == [(0,)]
    assert _q(out, "SELECT count(*) FROM edge") == [(0,)]
    assert check_file(out).ok


def test_many_values_in_one_cell_and_many_rows(tmp_path: Path) -> None:
    values = [f"v{i:05d}" for i in range(3000)]
    lines = ["code,tags", "A," + ";".join(values)]
    lines += [f"R{i},v{i:05d};v{(i + 1) % 3000:05d}" for i in range(500)]
    out = _build(tmp_path, "\n".join(lines) + "\n")
    assert _q(out, "SELECT count(*) FROM node WHERE type = 'Tag'") == [(3000,)]
    assert _q(out, "SELECT count(*) FROM edge") == [(3000 + 1000,)]
    assert check_file(out).ok


def test_a_long_value_under_the_csv_module_limit(tmp_path: Path) -> None:
    value = "x" * 100_000
    out = _build(tmp_path, f"code,tags\nA,{value};y\n")
    assert _tags(out) == [value, "y"]
    assert check_file(out).ok


def test_a_value_of_two_hundred_thousand_characters_is_not_refused(tmp_path: Path) -> None:
    # the spec sets no limit on the length of text (sections 3.1, 3.2); a hidden limit of the
    # CSV reader would make a valid source impossible to import
    value = "x" * 200_000
    out = _build(tmp_path, f"code,tags\nA,{value};y\n")
    assert _tags(out) == [value, "y"]
    assert check_file(out).ok


def test_non_ascii_values_in_latin_1(tmp_path: Path) -> None:
    settings = Settings(
        type="Item",
        key="code",
        encoding="latin-1",
        links={"tags": Link("Tag", "tagged", separator=";")},
    )
    path = tmp_path / "items.csv"
    path.write_bytes("code,tags\nA,caf\u00e9; na\u00efve\n".encode("latin-1"))
    out = tmp_path / "t.tessera"
    build(path, out, settings)
    assert _tags(out) == ["caf\u00e9", "na\u00efve"]


# --- refusals ------------------------------------------------------------------------------


def test_u0000_in_a_linked_cell_is_refused_naming_the_file_and_row(tmp_path: Path) -> None:
    # section 3.1: text MUST NOT contain U+0000
    path = _csv(tmp_path, "code,tags\nA,x\nB,y\x00z;w\n")
    with pytest.raises(ValueError, match=r"items\.csv.*\b2\b"):
        build(path, tmp_path / "t.tessera", TAGS)
    assert not (tmp_path / "t.tessera").exists()


def test_a_linked_column_the_header_has_twice_is_refused(tmp_path: Path) -> None:
    path = _csv(tmp_path, "code,tags,tags\nA,x,y\n")
    with pytest.raises(ValueError, match="tags"):
        build(path, tmp_path / "t.tessera", TAGS)
    assert not (tmp_path / "t.tessera").exists()


def test_a_linked_column_name_is_case_sensitive(tmp_path: Path) -> None:
    path = _csv(tmp_path, "code,Tags\nA,x\n")
    with pytest.raises(ValueError, match="tags"):
        build(path, tmp_path / "t.tessera", TAGS)


def test_the_row_key_column_cannot_be_a_linked_node_type_of_the_same_name(tmp_path: Path) -> None:
    # section 3.4: node ids are `type:key`; a link into the row type would collide with the rows
    settings = Settings(type="Item", key="code", links={"tags": Link("Item", "tagged")})
    with pytest.raises(ValueError, match="Item"):
        build(_csv(tmp_path, "code,tags\nA,x\n"), tmp_path / "t.tessera", settings)


@pytest.mark.parametrize("edge", ["Tagged", "1tag", "tag-ed", "", "tag ged", "t\u00e4g"])
def test_an_edge_type_outside_the_section_3_4_pattern_is_refused(tmp_path: Path, edge: str) -> None:
    settings = Settings(type="Item", key="code", links={"tags": Link("Tag", edge)})
    with pytest.raises(ValueError):
        build(_csv(tmp_path, "code,tags\nA,x\n"), tmp_path / "t.tessera", settings)
    assert not (tmp_path / "t.tessera").exists()


@pytest.mark.parametrize("node_type", ["tag", "_Tag", "Tag-1", "", "T ag", "\u00c9tag"])
def test_a_node_type_outside_the_section_3_4_pattern_is_refused(
    tmp_path: Path, node_type: str
) -> None:
    settings = Settings(type="Item", key="code", links={"tags": Link(node_type, "tagged")})
    with pytest.raises(ValueError):
        build(_csv(tmp_path, "code,tags\nA,x\n"), tmp_path / "t.tessera", settings)
    assert not (tmp_path / "t.tessera").exists()


@pytest.mark.parametrize("edge", ["a", "a1", "a_b", "a_1_b"])
def test_edge_types_the_pattern_allows_are_accepted(tmp_path: Path, edge: str) -> None:
    settings = Settings(type="Item", key="code", links={"tags": Link("Tag1", edge)})
    out = _build(tmp_path, "code,tags\nA,x\n", settings)
    assert check_file(out).ok


def test_the_source_file_is_unchanged_and_an_existing_output_is_kept(tmp_path: Path) -> None:
    path = _csv(tmp_path, "code,tags\nA,x;y\n")
    before = path.read_bytes()
    out = tmp_path / "t.tessera"
    out.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        build(path, out, TAGS)
    assert out.read_bytes() == b"keep me"
    assert path.read_bytes() == before


# --- determinism and recorded settings -------------------------------------------------------


def test_the_order_links_are_listed_in_does_not_change_the_output(tmp_path: Path) -> None:
    # section 4.3: same source and settings, same hash; JSON is canonical (section 3.1)
    one = Settings(
        type="Item",
        key="code",
        links={"a": Link("Aa", "has_a", separator=";"), "b": Link("Bb", "has_b", "in")},
    )
    two = Settings(
        type="Item",
        key="code",
        links={"b": Link("Bb", "has_b", "in"), "a": Link("Aa", "has_a", separator=";")},
    )
    text = "code,a,b\nX,p;q,r\nY,q,s\n"
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    first = build(_csv(tmp_path / "1", text), tmp_path / "1" / "t", one)
    second = build(_csv(tmp_path / "2", text), tmp_path / "2" / "t", two)
    assert first.knowledge_hash == second.knowledge_hash
    assert (tmp_path / "1" / "t").read_bytes() == (tmp_path / "2" / "t").read_bytes()


def test_the_column_order_of_the_csv_does_not_change_the_knowledge_hash(tmp_path: Path) -> None:
    # section 3.6: the hash is over canonical rows, not over the order of the source
    settings = Settings(
        type="Item",
        key="code",
        links={"a": Link("Aa", "has_a", separator=";"), "b": Link("Bb", "has_b")},
    )
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    one = build(_csv(tmp_path / "1", "code,a,b\nX,p;q,r\n"), tmp_path / "1" / "t", settings)
    two = build(_csv(tmp_path / "2", "b,code,a\nr,X,p;q\n"), tmp_path / "2" / "t", settings)
    # the source hash differs, so the hashes may differ; compare the graph instead
    q = "SELECT id, type FROM node ORDER BY nid"
    assert _q(tmp_path / "1" / "t", q) == _q(tmp_path / "2" / "t", q)
    assert (
        one.knowledge_hash != two.knowledge_hash
    )  # different source bytes, different `source` part


def test_a_changed_cell_changes_the_knowledge_hash(tmp_path: Path) -> None:
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    one = build(_csv(tmp_path / "1", "code,tags\nA,x;y\n"), tmp_path / "1" / "t", TAGS)
    two = build(_csv(tmp_path / "2", "code,tags\nA,x;z\n"), tmp_path / "2" / "t", TAGS)
    assert one.knowledge_hash != two.knowledge_hash


def test_header_settings_are_canonical_json_and_rebuild_the_same_file(tmp_path: Path) -> None:
    # sections 3.1, 3.3: header.settings records the settings; reading them back and
    # building again gives the same bytes
    settings = Settings(
        type="Item",
        key="code",
        label="code",
        links={"tags": Link("Tag", "tagged", "in", separator=" | ")},
    )
    text = "code,tags\nA,x | y\n"
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    build(_csv(tmp_path / "1", text), tmp_path / "1" / "t", settings)
    [(recorded,)] = _q(tmp_path / "1" / "t", "SELECT settings FROM header")
    parsed = json.loads(str(recorded))
    assert json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False) == recorded
    build(_csv(tmp_path / "2", text), tmp_path / "2" / "t", from_json(parsed))
    assert (tmp_path / "1" / "t").read_bytes() == (tmp_path / "2" / "t").read_bytes()


def test_a_separator_with_non_ascii_text_is_recorded_as_written(tmp_path: Path) -> None:
    settings = Settings(
        type="Item", key="code", links={"tags": Link("Tag", "tagged", separator="\u00b7")}
    )
    out = _build(tmp_path, "code,tags\nA,x\u00b7y\n", settings)
    [(recorded,)] = _q(out, "SELECT settings FROM header")
    assert json.loads(str(recorded))["links"]["tags"]["separator"] == "\u00b7"
    assert "\u00b7" in str(recorded)  # RFC 8785: escaped only where JSON requires it


# --- the settings file ----------------------------------------------------------------------


def _read(tmp_path: Path, text: str) -> Settings:
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    return read(path)


def test_empty_links_mapping_is_no_links(tmp_path: Path) -> None:
    assert _read(tmp_path, "type: Item\nlinks: {}\n") == Settings(type="Item")


def test_an_explicit_null_separator_is_no_separator(tmp_path: Path) -> None:
    got = _read(tmp_path, "links:\n  t: {type: Tag, edge: tagged, separator: null}\n")
    assert got.links["t"].separator is None


def test_a_separator_of_several_characters_with_spaces_keeps_them(tmp_path: Path) -> None:
    got = _read(tmp_path, 'links:\n  t: {type: Tag, edge: tagged, separator: " | "}\n')
    assert got.links["t"].separator == " | "


def test_a_tab_separator_in_yaml(tmp_path: Path) -> None:
    got = _read(tmp_path, 'links:\n  t: {type: Tag, edge: tagged, separator: "\\t"}\n')
    assert got.links["t"].separator == "\t"


def test_a_column_name_with_spaces_and_non_ascii_text_is_a_link_key(tmp_path: Path) -> None:
    got = _read(tmp_path, 'links:\n  "Cast \u00e9quipe": {type: Tag, edge: tagged}\n')
    assert list(got.links) == ["Cast \u00e9quipe"]


@pytest.mark.parametrize(
    ("entry", "line", "words"),
    [
        # block style: the line is the one holding the wrong setting
        ("  t:\n    type: Tag\n    edge: tagged\n    direction: up\n", 7, "direction"),
        ("  t:\n    type: Tag\n    edge: Bad\n    direction: in\n", 6, "edge"),
        ("  t:\n    type: Tag\n    edge: tagged\n    colour: red\n", 7, "colour"),
        ("  t:\n    edge: tagged\n", 4, "type"),
        # scalar of the wrong YAML kind
        ("  t: {type: Tag, edge: tagged, separator: 5}\n", 4, "separator"),
        ("  t: {type: Tag, edge: tagged, separator: [a]}\n", 4, "separator"),
        ("  t: {type: Tag, edge: tagged, separator: true}\n", 4, "separator"),
        ("  t: {type: 5, edge: tagged}\n", 4, "type"),
        ("  t: {type: Tag, edge: [x]}\n", 4, "edge"),
        ("  t: {type: Tag, edge: tagged, direction: IN}\n", 4, "direction"),
        ("  t: {type: Tag, edge: tagged, direction: ''}\n", 4, "direction"),
        ("  t: {type: Tag, edge: tagged, direction: null}\n", 4, "direction"),
        ("  t: Tag\n", 4, "t"),
        ("  t: null\n", 4, "t"),
        # the second link is the wrong one: the line moves with it
        ("  a: {type: Aa, edge: has_a}\n  b: {type: Bb, edge: Has_B}\n", 5, "edge"),
    ],
)
def test_a_wrong_link_names_file_line_and_setting_in_every_yaml_style(
    tmp_path: Path, entry: str, line: int, words: str
) -> None:
    # plan M1.1: "an error naming the file, the line and the setting"
    path = tmp_path / "s.yaml"
    path.write_text(f"type: Item\nkey: code\nlinks:\n{entry}", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        read(path)
    assert str(e.value).startswith(f"{path}:{line}: ")
    assert words in str(e.value)


def test_a_link_column_listed_twice_is_refused_naming_the_line(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(
        "type: Item\nlinks:\n  t: {type: Tag, edge: tagged}\n  t: {type: Tag, edge: tagged}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as e:
        read(path)
    assert str(e.value).startswith(f"{path}:4")


@pytest.mark.parametrize("links", ["- a\n- b\n", "x\n", "5\n", "true\n"])
def test_links_that_are_not_a_mapping_are_refused_naming_the_setting(
    tmp_path: Path, links: str
) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(
        "type: Item\nlinks:\n" + "".join(f"  {line}\n" for line in links.splitlines()),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="links") as e:
        read(path)
    assert str(e.value).startswith(f"{path}:")


# --- the CLI -------------------------------------------------------------------------------


def _cli_import(tmp_path: Path, csv_text: str, yaml_text: str, out: str = "o.tessera") -> int:
    (tmp_path / "rows.csv").write_bytes(csv_text.encode("utf-8"))
    (tmp_path / "s.yaml").write_text(yaml_text, encoding="utf-8")
    return main(
        [
            "import",
            "csv",
            str(tmp_path / "rows.csv"),
            "--settings",
            str(tmp_path / "s.yaml"),
            "-o",
            str(tmp_path / out),
        ]
    )


def test_cli_error_for_a_wrong_link_names_the_file_line_and_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    yaml = (
        "type: Item\nkey: code\nlinks:\n  tags:\n    type: Tag\n    edge: tagged\n"
        "    direction: up\n"
    )
    assert _cli_import(tmp_path, "code,tags\nA,x\n", yaml) == 1
    err = capsys.readouterr().err
    assert "s.yaml:7" in err and "direction" in err
    assert not (tmp_path / "o.tessera").exists()


def test_cli_error_for_a_linked_column_missing_from_the_csv_names_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    yaml = "type: Item\nkey: code\nlinks:\n  cast: {type: Person, edge: acted_in}\n"
    assert _cli_import(tmp_path, "code,tags\nA,x\n", yaml) == 1
    err = capsys.readouterr().err
    assert "rows.csv" in err and "cast" in err
    assert not (tmp_path / "o.tessera").exists()


def test_cli_error_for_u0000_in_a_linked_cell_names_the_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    yaml = "type: Item\nkey: code\nlinks:\n  tags: {type: Tag, edge: tagged}\n"
    assert _cli_import(tmp_path, "code,tags\nA,x\nB,y\x00\n", yaml) == 1
    err = capsys.readouterr().err
    assert "rows.csv" in err and "2" in err
    assert not (tmp_path / "o.tessera").exists()


def test_cli_two_imports_of_the_same_source_and_settings_are_byte_identical(
    tmp_path: Path,
) -> None:
    yaml = "type: Item\nkey: code\nlinks:\n  tags: {type: Tag, edge: tagged, separator: ';'}\n"
    csv_text = "code,tags\nA,x; y;;z\nB,y\nC,\n"
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    assert _cli_import(tmp_path / "one", csv_text, yaml) == 0
    assert _cli_import(tmp_path / "two", csv_text, yaml) == 0
    assert (tmp_path / "one" / "o.tessera").read_bytes() == (
        tmp_path / "two" / "o.tessera"
    ).read_bytes()
    assert main(["check", str(tmp_path / "one" / "o.tessera")]) == 0


def test_cli_header_settings_of_the_output_are_a_settings_file_for_the_same_output(
    tmp_path: Path,
) -> None:
    yaml = (
        "type: Item\nkey: code\nlinks:\n"
        "  tags: {type: Tag, edge: tagged, direction: in, separator: ';'}\n"
    )
    csv_text = "code,tags\nA,x;y\nB,y\n"
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    assert _cli_import(tmp_path / "one", csv_text, yaml) == 0
    [(recorded,)] = _q(tmp_path / "one" / "o.tessera", "SELECT settings FROM header")
    assert _cli_import(tmp_path / "two", csv_text, str(recorded)) == 0  # JSON is YAML
    assert (tmp_path / "one" / "o.tessera").read_bytes() == (
        tmp_path / "two" / "o.tessera"
    ).read_bytes()
