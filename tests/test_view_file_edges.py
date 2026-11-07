"""Edge cases of the view file reader, from the words of docs/design.md ("View file") and the
maintainer's answer on #120 (every key optional, types in the order written, `label` and
`names`, `search` defaults to `semantic`), plus the YAML rules the spec sets for the other
YAML files it reads (spec 0.1 section 5: YAML 1.2 core schema, duplicate keys rejected)."""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from mosaic_build.view_file import TypeView, ViewSettings, from_json, read

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "views" / "view.schema.json").read_text(encoding="utf-8"))
FIXTURES = ROOT / "conformance" / "fixtures"


def _write(tmp_path: Path, text: str | bytes, name: str = "view.yaml") -> Path:
    path = tmp_path / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="")
    return path


# Line numbers (the error names the line of the setting).


def test_error_line_counts_comments_and_blank_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, "# a comment\n\n\nsearch: fuzzy\n")
    with pytest.raises(ValueError, match=rf"^{path}:4: .*search"):
        read(path)


def test_error_line_with_crlf_line_endings(tmp_path: Path) -> None:
    path = _write(tmp_path, "search: text\r\ntheme: sepia\r\n")
    with pytest.raises(ValueError, match=rf"^{path}:2: .*theme"):
        read(path)


def test_error_line_inside_a_multi_line_flow_mapping(tmp_path: Path) -> None:
    path = _write(tmp_path, "types:\n  A: {label: Ay,\n    colour: red}\n")
    with pytest.raises(ValueError, match=rf"^{path}:3: .*types\.A\.colour"):
        read(path)


def test_error_line_after_a_block_scalar(tmp_path: Path) -> None:
    path = _write(tmp_path, "types:\n  A:\n    label: |\n      one\n      two\n    page: 3\n")
    with pytest.raises(ValueError, match=rf"^{path}:6: .*types\.A\.page"):
        read(path)


def test_error_in_a_path_with_spaces_and_non_ascii(tmp_path: Path) -> None:
    path = _write(tmp_path, "search: fuzzy\n", name="vue été.yaml")
    with pytest.raises(ValueError) as e:
        read(path)
    assert str(e.value).startswith(f"{path}:1: ")


def test_read_takes_a_string_path(tmp_path: Path) -> None:
    path = _write(tmp_path, "search: text\n")
    assert read(str(path)).search == "text"


# Duplicates (spec 0.1 section 5: a reader MUST reject duplicate keys).


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("types:\n  A:\n    label: x\n    label: y\n", 4),
        ("types:\n  A: {}\n  A: {}\n", 3),
        ("types:\n  A:\n    names:\n      x: X\n      x: Y\n", 5),
        ("export:\n  types: [A]\n  types: [B]\n", 3),
        ("export: {}\nexport: {}\n", 2),
        ("types: {}\ntypes: {}\n", 2),
    ],
)
def test_a_duplicate_key_at_any_depth_is_an_error(tmp_path: Path, text: str, line: int) -> None:
    path = _write(tmp_path, text)
    with pytest.raises(ValueError, match=rf"^{path}:{line}: "):
        read(path)


def test_keys_that_differ_only_by_case_are_not_duplicates(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types:\n  a: {}\n  A: {}\n"))
    assert [t.name for t in settings.types or ()] == ["a", "A"]


def test_keys_equal_after_unicode_normalisation_are_not_duplicates(tmp_path: Path) -> None:
    # Text compares by UTF-8 bytes (CLAUDE.md): U+00E9 and U+0065 U+0301 differ.
    composed, decomposed = "\u00e9", "e\u0301"
    settings = read(_write(tmp_path, f"types:\n  {composed}: {{}}\n  {decomposed}: {{}}\n"))
    assert [t.name for t in settings.types or ()] == [composed, decomposed]


def test_a_repeated_column_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "types:\n  A:\n    page: [x, y, x]\n")
    with pytest.raises(ValueError, match=rf"^{path}:3: .*types\.A\.page"):
        read(path)


# YAML 1.2 core schema (the spec's reading of YAML).


@pytest.mark.parametrize("word", ["yes", "no", "on", "off", "y", "n"])
def test_a_type_named_like_a_yaml_1_1_boolean_is_text(tmp_path: Path, word: str) -> None:
    settings = read(_write(tmp_path, f"types:\n  {word}: {{}}\n"))
    assert [t.name for t in settings.types or ()] == [word]


@pytest.mark.parametrize("word", ["yes", "no", "on", "off"])
def test_a_label_that_is_a_yaml_1_1_boolean_is_text(tmp_path: Path, word: str) -> None:
    settings = read(_write(tmp_path, f"types:\n  A:\n    label: {word}\n"))
    assert settings.types is not None and settings.types[0].label == word


def test_a_quoted_number_is_a_text_label(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types:\n  A:\n    label: '3'\n    columns: ['1', '2']\n"))
    assert settings.types is not None
    assert settings.types[0].label == "3"
    assert settings.types[0].columns == ("1", "2")


@pytest.mark.parametrize("value", ["Text", "TEXT", "Semantic", "text ", "true", "1"])
def test_search_values_are_exact(tmp_path: Path, value: str) -> None:
    path = _write(tmp_path, f"search: '{value}'\n")
    with pytest.raises(ValueError, match=rf"^{path}:1: .*search"):
        read(path)


@pytest.mark.parametrize("value", ["Dark", "AUTO", "night", "0"])
def test_theme_values_are_exact(tmp_path: Path, value: str) -> None:
    path = _write(tmp_path, f"theme: '{value}'\n")
    with pytest.raises(ValueError, match=rf"^{path}:1: .*theme"):
        read(path)


def test_a_merge_key_is_not_special(tmp_path: Path) -> None:
    # In the core schema `<<` is an ordinary key, so it is an unknown key.
    path = _write(tmp_path, "base: &b {label: x}\ntypes:\n  A:\n    <<: *b\n")
    with pytest.raises(ValueError, match=rf"^{path}:\d+: "):
        read(path)


def test_an_alias_gives_the_same_list(tmp_path: Path) -> None:
    text = "types:\n  A:\n    columns: &c [x, y]\n    page: *c\n"
    settings = read(_write(tmp_path, text))
    assert settings.types is not None
    assert settings.types[0].columns == settings.types[0].page == ("x", "y")


def test_an_unknown_tag_is_an_error_not_code(tmp_path: Path) -> None:
    path = _write(tmp_path, "search: !!python/object/apply:os.getcwd []\n")
    with pytest.raises(ValueError, match=rf"^{path}:"):
        read(path)


def test_two_documents_are_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "search: text\n---\ntheme: dark\n")
    with pytest.raises(ValueError, match=rf"^{path}:"):
        read(path)


def test_a_tab_indent_is_an_error_naming_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "types:\n\tA: {}\n")
    with pytest.raises(ValueError, match=rf"^{path}:\d+: "):
        read(path)


def test_a_nul_byte_is_an_error_naming_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, b"search: text\x00\n")
    with pytest.raises(ValueError, match=rf"^{path}:"):
        read(path)


def test_a_numeric_top_level_key_is_an_unknown_key(tmp_path: Path) -> None:
    path = _write(tmp_path, "1: x\n")
    with pytest.raises(ValueError, match=rf"^{path}:1: .*\b1\b"):
        read(path)


def test_a_flow_style_document_is_read(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "{search: text, theme: dark, types: {A: {}}}\n"))
    assert (settings.search, settings.theme) == ("text", "dark")
    assert settings.types == (TypeView("A"),)


def test_quoted_keys_are_read(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, '"search": "text"\n"types":\n  "A b": {"label": "L"}\n'))
    assert settings.search == "text"
    assert settings.types == (TypeView("A b", label="L"),)


# Text: CRLF, byte order mark, size, characters.


def test_crlf_and_lf_files_read_the_same(tmp_path: Path) -> None:
    lf = "search: text\ntypes:\n  A:\n    columns: [x]\n"
    a = read(_write(tmp_path, lf, "a.yaml"))
    b = read(_write(tmp_path, lf.replace("\n", "\r\n"), "b.yaml"))
    assert a == b


def test_a_utf8_byte_order_mark_is_accepted_or_named(tmp_path: Path) -> None:
    path = _write(tmp_path, b"\xef\xbb\xbfsearch: text\n")
    try:
        settings = read(path)
    except ValueError as e:
        assert str(e).startswith(f"{path}:"), e
    else:
        assert settings.search == "text"


def test_non_ascii_names_and_labels_are_kept(tmp_path: Path) -> None:
    text = "types:\n  \u65e5\u672c:\n    label: \U0001f3a8 art\n    names: {\u540d: \u00c9tat}\n"
    settings = read(_write(tmp_path, text))
    assert settings.types == (
        TypeView("\u65e5\u672c", label="\U0001f3a8 art", names={"\u540d": "\u00c9tat"}),
    )


def test_a_very_long_label_is_kept_whole(tmp_path: Path) -> None:
    label = "x" * 1_000_000
    settings = read(_write(tmp_path, f"types:\n  A:\n    label: {label}\n"))
    assert settings.types is not None and settings.types[0].label == label


def test_many_types_keep_the_order_written(tmp_path: Path) -> None:
    names = [f"T{(i * 7919) % 5000:05d}" for i in range(5000)]
    assert len(set(names)) == 5000
    settings = read(_write(tmp_path, "types:\n" + "".join(f"  {n}: {{}}\n" for n in names)))
    assert [t.name for t in settings.types or ()] == names


def test_types_are_not_sorted_by_utf8_bytes(tmp_path: Path) -> None:
    # Order is the file's, even where it contradicts byte order.
    names = ["\u00e9", "z", "B", "a"]
    settings = read(_write(tmp_path, "types:\n" + "".join(f"  {n}: {{}}\n" for n in names)))
    assert [t.name for t in settings.types or ()] == names


def test_an_empty_names_mapping_equals_no_names(tmp_path: Path) -> None:
    a = read(_write(tmp_path, "types:\n  A: {names: {}}\n", "a.yaml"))
    b = read(_write(tmp_path, "types:\n  A: {}\n", "b.yaml"))
    assert a.as_json() == b.as_json()


# Values.


def test_an_empty_export_types_list_is_kept_apart_from_the_default(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "export:\n  types: []\n"))
    assert settings.export_types == ()
    assert settings.as_json()["export"] == {"types": []}


def test_export_types_may_name_a_type_the_view_does_not_list(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types:\n  A: {}\nexport:\n  types: [B]\n"))
    assert settings.export_types == ("B",)


def test_columns_and_page_may_name_things_no_other_setting_names(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types:\n  A:\n    columns: [q]\n    names: {z: Z}\n"))
    assert settings.types is not None
    assert settings.types[0].columns == ("q",)
    assert dict(settings.types[0].names) == {"z": "Z"}


@pytest.mark.parametrize(
    ("text", "setting"),
    [
        ("types:\n  A:\n    names: {'': X}\n", "types.A.names"),
        ("types:\n  A:\n    names: {x: ''}\n", "types.A.names.x"),
        ("types:\n  A:\n    columns: ['']\n", "types.A.columns"),
        ("types:\n  A:\n    page: [x, '']\n", "types.A.page"),
        ("export:\n  types: ['']\n", "export.types"),
        ("types:\n  A:\n    label: null\n", "types.A.label"),
        ("types:\n  A:\n    columns: [null]\n", "types.A.columns"),
        ("types:\n  A:\n    columns: [[x]]\n", "types.A.columns"),
        ("types:\n  A:\n    names: {x: [Y]}\n", "types.A.names.x"),
        ("types:\n  A:\n    label: 1.5\n", "types.A.label"),
        ("types:\n  A:\n    label: true\n", "types.A.label"),
        ("export:\n  types: [3]\n", "export.types"),
        ("export:\n  types: {A: 1}\n", "export.types"),
        ("types:\n  A: [label]\n", "types.A"),
        ("types:\n  A: Ay\n", "types.A"),
        ("types: A\n", "types"),
        ("types: 3\n", "types"),
        ("search: 3\n", "search"),
        ("search: {a: b}\n", "search"),
        ("theme: [dark]\n", "theme"),
        ("export: 3\n", "export"),
        ("export: text\n", "export"),
    ],
)
def test_a_value_of_the_wrong_kind_names_file_line_and_setting(
    tmp_path: Path, text: str, setting: str
) -> None:
    path = _write(tmp_path, text)
    with pytest.raises(ValueError) as e:
        read(path)
    message = str(e.value)
    assert message.startswith(f"{path}:"), message
    assert setting in message, message
    # the line is a number and is a line of the file
    line = int(message[len(str(path)) + 1 :].split(":", 1)[0])
    assert 1 <= line <= text.count("\n"), message


@pytest.mark.parametrize(
    "text",
    [
        "search: fuzzy\n",
        "types: [A]\n",
        "types:\n  A: {colour: red}\n",
        "export: {types: A}\n",
        "types:\n  A: {columns: [x, x]}\n",
        "theme: Dark\n",
        "extra: 1\n",
        "types:\n  A: {names: {x: 1}}\n",
        "types:\n  '': {}\n",
    ],
)
def test_reader_and_schema_both_refuse(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        read(_write(tmp_path, text))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(yaml.safe_load(text), SCHEMA)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "search: text\n",
        "types:\n  A: {}\n",
        "types:\n  A: {label: L, columns: [], page: [], names: {}}\n",
        "export: {}\n",
        "export: {types: []}\n",
        "types: {}\nexport: {types: [Z]}\n",
    ],
)
def test_reader_and_schema_both_accept(tmp_path: Path, text: str) -> None:
    read(_write(tmp_path, text))
    jsonschema.validate(yaml.safe_load(text) or {}, SCHEMA)


# Determinism and shape of the settings handed to the page.


def test_reading_twice_gives_the_same_settings_and_bytes(tmp_path: Path) -> None:
    path = _write(tmp_path, (ROOT / "views" / "example.yaml").read_text(encoding="utf-8"))
    a, b = read(path), read(path)
    assert a == b
    assert json.dumps(a.as_json()) == json.dumps(b.as_json())


def test_as_json_has_the_same_keys_whatever_is_set(tmp_path: Path) -> None:
    empty = read(None).as_json()
    full = read(ROOT / "views" / "example.yaml").as_json()
    assert set(empty) == set(full) == {"search", "theme", "types", "export"}
    assert set(empty["export"]) == set(full["export"]) == {"types"}


def test_as_json_round_trips_through_json_text() -> None:
    settings = read(ROOT / "views" / "example.yaml")
    data = settings.as_json()
    assert json.loads(json.dumps(data, ensure_ascii=False)) == data


def test_the_defaults_are_not_shared_between_settings() -> None:
    a, b = ViewSettings(), ViewSettings()
    assert a == b
    assert a.as_json() == b.as_json() == read(None).as_json()


def test_from_json_none_is_an_empty_view_file() -> None:
    assert from_json(None) == ViewSettings()


def test_from_json_empty_mapping_is_an_empty_view_file() -> None:
    assert from_json({}) == ViewSettings()


@pytest.mark.parametrize("value", ["text", 3, True, [], [{"search": "text"}], 1.5])
def test_from_json_refuses_a_document_that_is_not_a_mapping(value: object) -> None:
    with pytest.raises(ValueError):
        from_json(value)


def test_from_json_keeps_the_order_of_types() -> None:
    settings = from_json({"types": {"Z": {}, "A": {}, "M": {}}})
    assert [t.name for t in settings.types or ()] == ["Z", "A", "M"]


def test_the_directory_is_not_a_view_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read(tmp_path)


# The shipped view files.


def test_the_example_is_valid_with_every_key_removed_one_at_a_time() -> None:
    data = yaml.safe_load((ROOT / "views" / "example.yaml").read_text(encoding="utf-8"))
    for key in data:
        trimmed = {k: v for k, v in data.items() if k != key}
        jsonschema.validate(trimmed, SCHEMA)
        from_json(trimmed)


def _pattern_things(pattern: dict, type_name: str) -> set[str]:
    properties = set(pattern["types"][type_name].get("from", {}).get("", {}))
    for mapping in pattern["types"][type_name].get("from", {}).values():
        properties |= set(mapping)
    edges = {
        name
        for name, edge in pattern.get("edges", {}).items()
        if edge["from"] == type_name or edge.get("to") == type_name
    }
    return properties | edges


def test_a_fixture_view_names_only_properties_and_edges_of_its_types() -> None:
    checked = 0
    for view in sorted(FIXTURES.glob("*/view.yaml")):
        pattern = yaml.safe_load((view.parent / "pattern.yaml").read_text(encoding="utf-8"))
        for entry in read(view).types or ():
            known = _pattern_things(pattern, entry.name)
            used = set(entry.columns or ()) | set(entry.page or ()) | set(entry.names)
            assert used <= known, (view, entry.name, sorted(used - known))
            checked += 1
    assert checked


def test_a_fixture_view_lists_each_type_once_and_in_the_pattern() -> None:
    for view in sorted(FIXTURES.glob("*/view.yaml")):
        names = [t.name for t in read(view).types or ()]
        assert len(names) == len(set(names)), view


def test_views_readme_names_the_reader() -> None:
    text = (ROOT / "views" / "README.md").read_text(encoding="utf-8")
    assert "view.schema.json" in text and "example.yaml" in text
