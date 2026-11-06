"""The CSV tessera builder, columns as linked things (plan M1.1; docs/design.md First milestone).

A column can become linked things: each value in its cells, split on an optional separator and
trimmed, is one node of the column's own type, keyed by the value, with one edge per row and
value pair (sections 3.4, 4.1). Every such node and edge has evidence pointing at the row and
the column, ``file=<name>;row=<n>;field=<column>`` (section 3.5). Empty cells and empty values
make nothing. The same file and settings give the same knowledge hash (section 4.3), and the
settings are recorded in ``header.settings`` (section 3.3).
"""

import json
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build.tessera.csv import Link, Settings, build
from mosaic_build.tessera.settings import from_json, read
from mosaic_format.check import check_file

CSV = (
    "code,title,makers,shelf\n"
    'B1,First,"Ann Lee, Bo Chan",north\n'
    'B2,Second,"Bo Chan,  Cy Dow ",north\n'
    "B3,Third,,south\n"
    'B4,Fourth,"Ann Lee, , Ann Lee,\u00a0",\n'
)

SETTINGS = Settings(
    type="Book",
    key="code",
    label="title",
    links={
        "makers": Link(type="Maker", edge="made_by", separator=","),
        "shelf": Link(type="Shelf", edge="holds", direction="in"),
    },
)


def _write(tmp_path: Path, text: str, name: str = "books.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _build(tmp_path: Path, settings: Settings = SETTINGS, text: str = CSV) -> Path:
    out = tmp_path / "books.tessera"
    build(_write(tmp_path, text), out, settings)
    return out


def _q(path: Path, sql: str) -> list[tuple[object, ...]]:
    with mosaic_format.open(path) as f:
        return f.query(sql)


def test_one_node_per_distinct_trimmed_value_keyed_by_the_value(tmp_path: Path) -> None:
    out = _build(tmp_path)
    makers = _q(out, "SELECT id, key, label FROM v_node WHERE type = 'Maker' ORDER BY id")
    assert makers == [
        ("Maker:Ann Lee", "Ann Lee", None),
        ("Maker:Bo Chan", "Bo Chan", None),
        ("Maker:Cy Dow", "Cy Dow", None),
    ]
    shelves = _q(out, "SELECT id, key FROM v_node WHERE type = 'Shelf' ORDER BY id")
    assert shelves == [("Shelf:north", "north"), ("Shelf:south", "south")]


def test_one_edge_per_row_and_value_pair_in_the_given_direction(tmp_path: Path) -> None:
    out = _build(tmp_path)
    edges = _q(out, "SELECT src, type, dst, qualifier FROM v_edge ORDER BY src, type, dst")
    assert edges == [
        ("Book:B1", "made_by", "Maker:Ann Lee", ""),
        ("Book:B1", "made_by", "Maker:Bo Chan", ""),
        ("Book:B2", "made_by", "Maker:Bo Chan", ""),
        ("Book:B2", "made_by", "Maker:Cy Dow", ""),
        ("Book:B4", "made_by", "Maker:Ann Lee", ""),
        ("Shelf:north", "holds", "Book:B1", ""),
        ("Shelf:north", "holds", "Book:B2", ""),
        ("Shelf:south", "holds", "Book:B3", ""),
    ]


def test_linked_types_and_edge_types_are_declared(tmp_path: Path) -> None:
    out = _build(tmp_path)
    types = _q(
        out, "SELECT name, kind, key_prop, from_type, to_type, props FROM type ORDER BY name"
    )
    assert types == [
        ("Book", "node", "code", None, None, "{}"),
        ("Maker", "node", "makers", None, None, "{}"),
        ("Shelf", "node", "shelf", None, None, "{}"),
        ("holds", "edge", None, "Shelf", "Book", "{}"),
        ("made_by", "edge", None, "Book", "Maker", "{}"),
    ]


def test_every_linked_node_has_evidence_for_each_row_and_column_it_occurs_in(
    tmp_path: Path,
) -> None:
    out = _build(tmp_path)
    rows = _q(
        out,
        "SELECT n.id, e.locator, e.method, e.prop FROM v_evidence e JOIN v_node n "
        "ON e.node = n.id WHERE n.type = 'Maker' ORDER BY n.id, e.locator",
    )
    assert rows == [
        ("Maker:Ann Lee", "file=books.csv;row=1;field=makers", "extracted", None),
        ("Maker:Ann Lee", "file=books.csv;row=4;field=makers", "extracted", None),
        ("Maker:Bo Chan", "file=books.csv;row=1;field=makers", "extracted", None),
        ("Maker:Bo Chan", "file=books.csv;row=2;field=makers", "extracted", None),
        ("Maker:Cy Dow", "file=books.csv;row=2;field=makers", "extracted", None),
    ]


def test_every_edge_has_evidence_pointing_at_its_row_and_column(tmp_path: Path) -> None:
    out = _build(tmp_path)
    rows = _q(
        out,
        "SELECT edge_src, edge_dst, locator FROM v_evidence WHERE edge_type IS NOT NULL "
        "ORDER BY edge_src, edge_dst",
    )
    assert rows == [
        ("Book:B1", "Maker:Ann Lee", "file=books.csv;row=1;field=makers"),
        ("Book:B1", "Maker:Bo Chan", "file=books.csv;row=1;field=makers"),
        ("Book:B2", "Maker:Bo Chan", "file=books.csv;row=2;field=makers"),
        ("Book:B2", "Maker:Cy Dow", "file=books.csv;row=2;field=makers"),
        ("Book:B4", "Maker:Ann Lee", "file=books.csv;row=4;field=makers"),
        ("Shelf:north", "Book:B1", "file=books.csv;row=1;field=shelf"),
        ("Shelf:north", "Book:B2", "file=books.csv;row=2;field=shelf"),
        ("Shelf:south", "Book:B3", "file=books.csv;row=3;field=shelf"),
    ]


def test_empty_cells_and_empty_or_white_space_values_make_nothing(tmp_path: Path) -> None:
    out = _build(tmp_path)
    # B3 has an empty makers cell, B4 an empty shelf cell; B4's makers hold an empty value
    # and a lone U+00A0 (Unicode White_Space) between separators.
    assert _q(out, "SELECT count(*) FROM v_edge WHERE src = 'Book:B3' AND type = 'made_by'") == [
        (0,)
    ]
    assert _q(out, "SELECT count(*) FROM v_edge WHERE dst = 'Book:B4' AND type = 'holds'") == [(0,)]
    keys = [k for (k,) in _q(out, "SELECT key FROM v_node WHERE type = 'Maker'")]
    assert "" not in keys and "\u00a0" not in keys


def test_a_value_twice_in_one_cell_is_one_edge_with_one_evidence_row(tmp_path: Path) -> None:
    out = _build(tmp_path)
    rows = _q(
        out,
        "SELECT count(*) FROM v_evidence WHERE edge_src = 'Book:B4' AND edge_dst = 'Maker:Ann Lee'",
    )
    assert rows == [(1,)]


def test_without_a_separator_a_cell_is_one_value_trimmed(tmp_path: Path) -> None:
    text = 'code,makers\nB1,"Ann Lee, Bo Chan"\nB2," Ann Lee "\n'
    settings = Settings(type="Book", key="code", links={"makers": Link("Maker", "made_by")})
    out = _build(tmp_path, settings, text)
    keys = _q(out, "SELECT key FROM v_node WHERE type = 'Maker' ORDER BY key")
    assert keys == [("Ann Lee",), ("Ann Lee, Bo Chan",)]


def test_the_tessera_passes_the_checker(tmp_path: Path) -> None:
    out = _build(tmp_path)
    assert check_file(out).ok


def test_the_same_file_and_settings_give_the_same_knowledge_hash(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = build(_write(a, CSV), a / "t.tessera", SETTINGS)
    second = build(_write(b, CSV), b / "t.tessera", SETTINGS)
    assert first.knowledge_hash == second.knowledge_hash
    assert (a / "t.tessera").read_bytes() == (b / "t.tessera").read_bytes()


def test_the_link_settings_are_recorded_in_header_settings(tmp_path: Path) -> None:
    out = _build(tmp_path)
    [(text,)] = _q(out, "SELECT settings FROM header")
    recorded = json.loads(str(text))
    assert recorded["links"] == {
        "makers": {"type": "Maker", "edge": "made_by", "direction": "out", "separator": ","},
        "shelf": {"type": "Shelf", "edge": "holds", "direction": "in", "separator": None},
    }
    assert from_json(recorded) == SETTINGS


def test_settings_without_links_record_no_links() -> None:
    assert "links" not in json.loads(Settings().as_json())


def test_a_yaml_settings_file_with_links(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        """\
type: Book
key: code
label: title
links:
  makers: {type: Maker, edge: made_by, separator: ","}
  shelf: {type: Shelf, edge: holds, direction: in}
""",
        encoding="utf-8",
    )
    assert read(path) == SETTINGS


@pytest.mark.parametrize(
    ("links", "line", "words"),
    [
        ("  makers: {type: maker, edge: made_by}\n", 4, "type"),
        ("  makers: {type: Maker, edge: MadeBy}\n", 4, "edge"),
        ("  makers: {type: Maker, edge: made_by, direction: up}\n", 4, "direction"),
        ("  makers: {type: Maker, edge: made_by, separator: ''}\n", 4, "separator"),
        ("  makers: {type: Maker, edge: made_by, colour: red}\n", 4, "colour"),
        ("  makers: {edge: made_by}\n", 4, "type"),
        ("  makers: [Maker, made_by]\n", 4, "makers"),
    ],
)
def test_a_wrong_link_setting_names_the_file_the_line_and_the_setting(
    tmp_path: Path, links: str, line: int, words: str
) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(f"type: Book\nkey: code\nlinks:\n{links}", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        read(path)
    message = str(e.value)
    assert message.startswith(f"{path}:{line}: settings: ")
    assert "links.makers" in message and words in message


MAKERS = "  makers: {type: Maker, edge: made_by}\n"
SAME_TYPE = MAKERS + "  shelf:\n    edge: holds\n    type: Maker\n"
SAME_EDGE = MAKERS + "  shelf:\n    type: Shelf\n    edge: made_by\n"


@pytest.mark.parametrize(
    ("links", "line", "words"),
    [
        ("  makers: {type: Book, edge: made_by}\n", 4, "'Book' is already the type of the rows"),
        (
            SAME_TYPE,
            7,
            "links.shelf: type 'Maker' is already the type of links.makers",
        ),
        (
            SAME_EDGE,
            7,
            "links.shelf: edge 'made_by' is already the edge of links.makers",
        ),
    ],
)
def test_colliding_links_in_a_settings_file_name_the_file_the_line_and_the_setting(
    tmp_path: Path, links: str, line: int, words: str
) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(f"type: Book\nkey: code\nlinks:\n{links}", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        read(path)
    assert str(e.value).startswith(f"{path}:{line}: settings: ")
    assert words in str(e.value)


@pytest.mark.parametrize(
    ("links", "words"),
    [
        ({"makers": Link("Book", "made_by")}, "Book"),
        ({"makers": Link("Maker", "made_by"), "shelf": Link("Maker", "holds")}, "Maker"),
        ({"makers": Link("Maker", "made_by"), "shelf": Link("Shelf", "made_by")}, "made_by"),
    ],
)
def test_link_settings_that_would_collide_are_refused(
    tmp_path: Path, links: dict[str, Link], words: str
) -> None:
    settings = Settings(type="Book", key="code", links=links)
    with pytest.raises(ValueError, match=words):
        _build(tmp_path, settings)
    assert not (tmp_path / "books.tessera").exists()


def test_a_linked_column_missing_from_the_header_is_named(tmp_path: Path) -> None:
    settings = Settings(type="Book", key="code", links={"authors": Link("Maker", "made_by")})
    with pytest.raises(ValueError, match=r"books\.csv: column 'authors' is not in the header"):
        _build(tmp_path, settings)


def test_a_linked_column_whose_name_cannot_be_a_locator_value_is_refused(tmp_path: Path) -> None:
    text = "code,a;b\nB1,x\n"
    settings = Settings(type="Book", key="code", links={"a;b": Link("Thing", "has")})
    with pytest.raises(ValueError, match=r"section 3\.5"):
        _build(tmp_path, settings, text)
