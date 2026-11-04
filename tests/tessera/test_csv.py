"""The CSV tessera builder, rows (issue #11; Specification 0.1 sections 3.3 to 3.6 and 4).

One CSV file gives one tessera (section 4.1): one source of kind ``file`` holding the hash of
the file's bytes, one node per data row with its props, and evidence ``file=<name>;row=<n>``
on every node, ``row`` counting data rows from 1 after the header, method ``extracted``. The
settings that shaped the output are recorded in ``header.settings`` (section 3.3), and the same
file and settings give the same knowledge hash (section 4.3).
"""

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build import __version__
from mosaic_build.tessera.csv import Settings, build

DATA = Path(__file__).parent / "data"
ROWS = DATA / "rows.csv"
PRODUCER = f"mosaic-csv/{__version__}"

SETTINGS = Settings(
    type="Instrument",
    key="code",
    label="name",
    summary="notes",
    props=("family", "range"),
)


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with mosaic_format.open(path) as f:
        return f.query(sql)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.fixture
def built(tmp_path: Path) -> Path:
    out = tmp_path / "rows.tessera"
    build(ROWS, out, SETTINGS)
    return out


# --- the expected rows ---------------------------------------------------------------------


def test_one_node_per_data_row_with_label_summary_and_props(built: Path) -> None:
    nodes = _rows(built, "SELECT id, type, key, label, summary, props FROM node ORDER BY nid")
    assert nodes == [
        ("Instrument:H2", "Instrument", "H2", "Horn", "Coiled tube;\nrotary valves",
         '{"family":"brass"}'),
        ("Instrument:L4", "Instrument", "L4", "Lute", None, None),
        ("Instrument:O3", "Instrument", "O3", "Oboe", None,
         '{"family":"woodwind","range":"Bb3 upward"}'),
        ("Instrument:V1", "Instrument", "V1", "Viola", "Played under the chin",
         '{"family":"strings","range":"C3, upward"}'),
    ]  # fmt: skip


def test_evidence_locates_each_row_counting_data_rows_from_one(built: Path) -> None:
    evidence = _rows(
        built,
        "SELECT n.id, e.eid, e.prop, s.id, e.locator, e.method, e.producer, e.confidence, e.via"
        " FROM evidence e JOIN node n USING (nid) JOIN source s USING (sid) ORDER BY e.evid",
    )
    # The quoted line break in row 2 does not start a new row.
    assert evidence == [
        ("Instrument:H2", None, None, "rows.csv", "file=rows.csv;row=2", "extracted",
         PRODUCER, None, None),
        ("Instrument:L4", None, None, "rows.csv", "file=rows.csv;row=4", "extracted",
         PRODUCER, None, None),
        ("Instrument:O3", None, None, "rows.csv", "file=rows.csv;row=3", "extracted",
         PRODUCER, None, None),
        ("Instrument:V1", None, None, "rows.csv", "file=rows.csv;row=1", "extracted",
         PRODUCER, None, None),
    ]  # fmt: skip


def test_the_one_source_is_the_file_with_the_hash_of_its_bytes(built: Path) -> None:
    sources = _rows(built, "SELECT id, kind, path, hash, notice FROM source")
    digest = hashlib.sha256(ROWS.read_bytes()).hexdigest()
    assert sources == [("rows.csv", "file", "rows.csv", digest, None)]


def test_the_node_type_is_declared_with_its_props_as_text(built: Path) -> None:
    types = _rows(built, "SELECT name, kind, key_prop, from_type, to_type, props FROM type")
    assert types == [
        ("Instrument", "node", "code", None, None, '{"family":"text","range":"text"}'),
    ]


def test_the_header_is_a_tessera_recording_its_producer_and_settings(built: Path) -> None:
    (header,) = _rows(
        built,
        "SELECT format_version, kind, producer, settings, vector_hash, embed_model,"
        " pattern_hash, target, ai_model FROM header",
    )
    assert header[:3] == ("0.1", "tessera", PRODUCER)
    assert json.loads(str(header[3])) == {
        "type": "Instrument",
        "key": "code",
        "label": "name",
        "summary": "notes",
        "props": ["family", "range"],
        "encoding": "utf-8",
        "delimiter": ",",
    }
    assert header[4:] == (None, None, None, None, None)


def test_settings_are_canonical_json_text(built: Path) -> None:
    (settings,) = _rows(built, "SELECT settings FROM header")[0]
    value = json.loads(str(settings))
    expected = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert settings == expected


def test_nothing_but_nodes_evidence_and_search_is_filled(built: Path) -> None:
    for table in ("edge", "alias", "snippet", "mention", "link_count", "vector", "source_text",
                  "external_ref"):  # fmt: skip
        assert _rows(built, f"SELECT count(*) FROM {table}") == [(0,)], table
    assert _rows(built, "SELECT count(*) FROM search") == [(4,)]


def test_the_tessera_opens_by_the_reading_rules(built: Path) -> None:
    with mosaic_format.open(built) as f:
        assert f.kind == "tessera"
        assert len(f.knowledge_hash) == 64


def test_the_result_reports_the_knowledge_hash_of_the_file(built: Path) -> None:
    out = built.with_name("again.tessera")
    sealed = build(ROWS, out, SETTINGS)
    assert sealed.path == out
    with mosaic_format.open(out) as f:
        assert sealed.knowledge_hash == f.knowledge_hash


# --- determinism (section 4.3) -------------------------------------------------------------


def test_the_same_file_and_settings_give_the_same_knowledge_hash_twice(tmp_path: Path) -> None:
    first = build(ROWS, tmp_path / "a.tessera", SETTINGS)
    second = build(ROWS, tmp_path / "b.tessera", SETTINGS)
    assert first.knowledge_hash == second.knowledge_hash


def test_the_hash_does_not_depend_on_where_the_file_lies(tmp_path: Path) -> None:
    elsewhere = tmp_path / "deeper" / "dir"
    elsewhere.mkdir(parents=True)
    copy = elsewhere / ROWS.name
    shutil.copyfile(ROWS, copy)
    first = build(ROWS, tmp_path / "a.tessera", SETTINGS)
    second = build(copy, tmp_path / "b.tessera", SETTINGS)
    assert first.knowledge_hash == second.knowledge_hash
    assert _rows(tmp_path / "b.tessera", "SELECT path FROM source") == [("rows.csv",)]


def test_different_bytes_give_a_different_source_hash(tmp_path: Path) -> None:
    crlf = _write(tmp_path, "rows.csv", ROWS.read_bytes().replace(b"\n", b"\r\n"))
    a = build(ROWS, tmp_path / "a.tessera", SETTINGS)
    b = build(crlf, tmp_path / "b.tessera", SETTINGS)
    assert a.knowledge_hash != b.knowledge_hash
    # CRLF line ends are read like LF ones, apart from the quoted line break, kept as written.
    labels = _rows(tmp_path / "b.tessera", "SELECT label FROM node ORDER BY nid")
    assert labels == [("Horn",), ("Lute",), ("Oboe",), ("Viola",)]


# --- keys ----------------------------------------------------------------------------------


def test_without_a_key_column_the_row_position_is_the_key(tmp_path: Path) -> None:
    out = tmp_path / "rows.tessera"
    build(ROWS, out, Settings(label="name"))
    assert _rows(out, "SELECT id, type, key, label, props FROM node ORDER BY nid") == [
        ("Row:1", "Row", "1", "Viola", None),
        ("Row:2", "Row", "2", "Horn", None),
        ("Row:3", "Row", "3", "Oboe", None),
        ("Row:4", "Row", "4", "Lute", None),
    ]
    assert _rows(out, "SELECT name, key_prop, props FROM type") == [("Row", None, "{}")]
    (settings,) = _rows(out, "SELECT settings FROM header")[0]
    assert json.loads(str(settings))["key"] is None


def test_key_values_are_kept_as_written(tmp_path: Path) -> None:
    csv = _write(tmp_path, "keys.csv", b"k\n a \nA\na\n")
    out = tmp_path / "keys.tessera"
    build(csv, out, Settings(key="k"))
    keys = _rows(out, "SELECT key FROM node ORDER BY nid")
    assert keys == [(" a ",), ("A",), ("a",)]


def test_a_duplicate_key_is_refused_naming_both_rows(tmp_path: Path) -> None:
    csv = _write(tmp_path, "dup.csv", b"k,v\nx,1\ny,2\nx,3\n")
    out = tmp_path / "dup.tessera"
    with pytest.raises(ValueError, match=r"dup\.csv.*rows 1 and 3.*'x'"):
        build(csv, out, Settings(key="k"))
    assert not out.exists()


def test_an_empty_key_is_refused_naming_the_row(tmp_path: Path) -> None:
    csv = _write(tmp_path, "empty.csv", b"k,v\nx,1\n,2\n")
    with pytest.raises(ValueError, match=r"empty\.csv.*row 2.*'k'.*empty"):
        build(csv, tmp_path / "empty.tessera", Settings(key="k"))


# --- columns -------------------------------------------------------------------------------


def test_empty_cells_make_no_prop_label_or_summary(tmp_path: Path) -> None:
    csv = _write(tmp_path, "gaps.csv", b"a,b,c\n,,\nx,,z\n")
    out = tmp_path / "gaps.tessera"
    build(csv, out, Settings(label="a", summary="b", props=("b", "c")))
    rows = _rows(out, "SELECT key, label, summary, props FROM node ORDER BY nid")
    assert rows == [("1", None, None, None), ("2", "x", None, '{"c":"z"}')]


def test_props_keep_whitespace_and_quotes_as_written(tmp_path: Path) -> None:
    csv = _write(tmp_path, "q.csv", b'k,v\n1," say ""hi"" "\n')
    out = tmp_path / "q.tessera"
    build(csv, out, Settings(key="k", props=("v",)))
    (props,) = _rows(out, "SELECT props FROM node")[0]
    assert json.loads(str(props)) == {"v": ' say "hi" '}


def test_prop_keys_are_ordered_by_utf16_code_units(tmp_path: Path) -> None:
    # U+FF5E sorts after U+1F600 by code point but before it by UTF-16 code units (RFC 8785).
    bmp, astral = chr(0xFF5E), chr(0x1F600)
    header = f"k,{astral},{bmp},b,B\n".encode()
    csv = _write(tmp_path, "keys.csv", header + b"1,w,x,y,z\n")
    out = tmp_path / "keys.tessera"
    build(csv, out, Settings(key="k", props=(astral, bmp, "b", "B")))
    (props,) = _rows(out, "SELECT props FROM node")[0]
    assert props == f'{{"B":"z","b":"y","{astral}":"w","{bmp}":"x"}}'


def test_columns_not_named_in_the_settings_are_left_out(tmp_path: Path) -> None:
    out = tmp_path / "rows.tessera"
    build(ROWS, out, Settings(key="code"))
    rows = _rows(out, "SELECT id, label, summary, props FROM node ORDER BY nid")
    assert rows == [
        ("Row:H2", None, None, None),
        ("Row:L4", None, None, None),
        ("Row:O3", None, None, None),
        ("Row:V1", None, None, None),
    ]


@pytest.mark.parametrize(
    "settings",
    [
        Settings(key="nope"),
        Settings(label="nope"),
        Settings(summary="nope"),
        Settings(props=("family", "nope")),
    ],
)
def test_a_column_that_is_not_in_the_header_is_refused(tmp_path: Path, settings: Settings) -> None:
    with pytest.raises(ValueError, match=r"rows\.csv.*'nope'.*not in the header"):
        build(ROWS, tmp_path / "x.tessera", settings)


def test_a_setting_naming_a_column_the_header_has_twice_is_refused(tmp_path: Path) -> None:
    csv = _write(tmp_path, "twice.csv", b"a,b,a\n1,2,3\n")
    with pytest.raises(ValueError, match=r"twice\.csv.*'a'.*twice"):
        build(csv, tmp_path / "x.tessera", Settings(props=("a",)))
    out = tmp_path / "ok.tessera"
    build(csv, out, Settings(props=("b",)))  # a column used by no setting may repeat
    assert _rows(out, "SELECT props FROM node") == [('{"b":"2"}',)]


def test_a_prop_named_twice_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"'family'.*twice"):
        build(ROWS, tmp_path / "x.tessera", Settings(props=("family", "family")))


def test_a_row_with_the_wrong_number_of_fields_is_refused_naming_it(tmp_path: Path) -> None:
    csv = _write(tmp_path, "ragged.csv", b"a,b\n1,2\n3\n")
    with pytest.raises(ValueError, match=r"ragged\.csv.*row 2.*1 field.*header has 2"):
        build(csv, tmp_path / "x.tessera", Settings())


def test_blank_lines_are_not_rows(tmp_path: Path) -> None:
    csv = _write(tmp_path, "blank.csv", b"a\nx\n\ny\n")
    out = tmp_path / "blank.tessera"
    build(csv, out, Settings(key="a"))
    assert _rows(out, "SELECT e.locator FROM evidence e ORDER BY evid") == [
        ("file=blank.csv;row=1",),
        ("file=blank.csv;row=2",),
    ]


def test_a_file_without_a_header_row_is_refused(tmp_path: Path) -> None:
    csv = _write(tmp_path, "void.csv", b"")
    with pytest.raises(ValueError, match=r"void\.csv.*no header row"):
        build(csv, tmp_path / "x.tessera", Settings())


def test_a_header_without_rows_gives_a_tessera_without_nodes(tmp_path: Path) -> None:
    csv = _write(tmp_path, "head.csv", b"a,b\n")
    out = tmp_path / "head.tessera"
    build(csv, out, Settings(key="a", props=("b",)))
    assert _rows(out, "SELECT count(*) FROM node") == [(0,)]
    assert _rows(out, "SELECT name, props FROM type") == [("Row", '{"b":"text"}')]


def test_bad_quoting_is_refused_naming_the_line(tmp_path: Path) -> None:
    csv = _write(tmp_path, "quote.csv", b'a,b\n1,"x"y\n')
    with pytest.raises(ValueError, match=r"quote\.csv.*line 2"):
        build(csv, tmp_path / "x.tessera", Settings())


def test_u0000_in_a_cell_is_refused_naming_the_row(tmp_path: Path) -> None:
    csv = _write(tmp_path, "nul.csv", b"a,b\n1,x\x00y\n")
    with pytest.raises(ValueError, match=r"nul\.csv.*row 1.*'b'.*U\+0000"):
        build(csv, tmp_path / "x.tessera", Settings(props=("b",)))


# --- encoding and delimiter ----------------------------------------------------------------


def test_the_encoding_and_delimiter_are_honoured(tmp_path: Path) -> None:
    csv = _write(tmp_path, "latin.csv", "id;name\n1;Café, très\n".encode("latin-1"))
    out = tmp_path / "latin.tessera"
    build(csv, out, Settings(key="id", label="name", encoding="latin-1", delimiter=";"))
    assert _rows(out, "SELECT label FROM node") == [("Café, très",)]
    (settings,) = _rows(out, "SELECT settings FROM header")[0]
    value = json.loads(str(settings))
    assert (value["encoding"], value["delimiter"]) == ("latin-1", ";")


def test_a_tab_delimiter(tmp_path: Path) -> None:
    csv = _write(tmp_path, "tabs.tsv", b"id\tname\n1\ta, b\n")
    out = tmp_path / "tabs.tessera"
    build(csv, out, Settings(key="id", label="name", delimiter="\t"))
    assert _rows(out, "SELECT label FROM node") == [("a, b",)]
    assert _rows(out, "SELECT locator FROM evidence") == [("file=tabs.tsv;row=1",)]


def test_a_utf8_byte_order_mark_is_not_part_of_the_first_column(tmp_path: Path) -> None:
    csv = _write(tmp_path, "bom.csv", b"\xef\xbb\xbfid,name\n1,x\n")
    out = tmp_path / "bom.tessera"
    build(csv, out, Settings(key="id", label="name"))
    assert _rows(out, "SELECT key_prop FROM type") == [("id",)]


def test_bytes_that_do_not_decode_are_refused(tmp_path: Path) -> None:
    csv = _write(tmp_path, "bad.csv", b"a\n\xff\n")
    with pytest.raises(ValueError, match=r"bad\.csv.*utf-8.*byte offset 2"):
        build(csv, tmp_path / "x.tessera", Settings())


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (Settings(type="row"), r"type 'row'.*\[A-Z\]"),
        (Settings(type="Row-1"), r"type 'Row-1'"),
        (Settings(delimiter=",,"), r"delimiter.*one character"),
        (Settings(delimiter='"'), r"delimiter"),
        (Settings(delimiter="\n"), r"delimiter"),
        (Settings(encoding="no-such-codec"), r"encoding 'no-such-codec'"),
    ],
)
def test_bad_settings_are_refused(tmp_path: Path, settings: Settings, message: str) -> None:
    out = tmp_path / "x.tessera"
    with pytest.raises(ValueError, match=message):
        build(ROWS, out, settings)
    assert not out.exists()


def test_a_file_name_that_cannot_be_a_locator_value_is_refused(tmp_path: Path) -> None:
    csv = _write(tmp_path, "a;b.csv", b"k\n1\n")
    with pytest.raises(ValueError, match=r"'a;b\.csv'.*locator"):
        build(csv, tmp_path / "x.tessera", Settings())


def test_an_existing_output_is_never_overwritten(built: Path) -> None:
    before = built.read_bytes()
    with pytest.raises(FileExistsError):
        build(ROWS, built, SETTINGS)
    assert built.read_bytes() == before


def test_the_source_file_is_never_written(tmp_path: Path) -> None:
    csv = _write(tmp_path, "rows.csv", ROWS.read_bytes())
    csv.chmod(0o444)
    build(csv, tmp_path / "rows.tessera", SETTINGS)
    assert csv.read_bytes() == ROWS.read_bytes()


def test_the_file_is_a_plain_sealed_sqlite_tessera(built: Path) -> None:
    con = sqlite3.connect(f"file:{built}?mode=ro", uri=True)
    try:
        assert con.execute("PRAGMA application_id").fetchone() == (mosaic_format.APPLICATION_ID,)
    finally:
        con.close()
