"""The view file: its settings, their defaults and its errors (plan M3.5).

docs/design.md, Implementation plan, "View file": YAML, used by both ``mosaic view`` and
``mosaic export``; it sets which types appear, columns, what a node page shows, labels, theme,
which types an export carries, and ``search: semantic`` or ``search: text``. The keys, values
and defaults are those of ``views/example.yaml`` (the maintainer's answer on #120): every key
is optional, so an empty view file, or none, gives M2's viewer; types appear in the order the
file writes them; ``label`` relabels a type and ``names`` its property and edge names;
``search`` defaults to ``semantic``. What ``export.types`` means is left to M3.10.
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from mosaic_build.view_file import TypeView, ViewSettings, from_json, read

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "views" / "view.schema.json"
EXAMPLE = ROOT / "views" / "example.yaml"
FIXTURES = ROOT / "conformance" / "fixtures"


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "view.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# Defaults: no view file, or an empty one, is M2's viewer.

M2_VIEWER = {
    "search": "semantic",
    "theme": "auto",
    "types": None,
    "export": {"types": None},
}
"""M2's viewer as settings: semantic search, the system's theme, every node type by name with
every property and edge, the mosaic's own names, and the export's types left to M3.10."""


def test_no_view_file_gives_m2s_viewer() -> None:
    assert read(None) == ViewSettings()
    assert read(None).as_json() == M2_VIEWER


@pytest.mark.parametrize("text", ["", "\n", "# only a comment\n", "{}\n", "---\n"])
def test_an_empty_view_file_gives_m2s_viewer(tmp_path: Path, text: str) -> None:
    assert read(_write(tmp_path, text)).as_json() == M2_VIEWER


def test_each_setting_has_its_default() -> None:
    settings = ViewSettings()
    assert settings.search == "semantic"
    assert settings.theme == "auto"
    assert settings.types is None  # every node type, by name
    assert settings.export_types is None  # meaning and default: M3.10
    entry = TypeView("A")
    assert entry.label is None  # the type name
    assert entry.columns is None  # every declared property
    assert entry.page is None  # every property and every edge type
    assert dict(entry.names) == {}  # the mosaic's own names


def test_a_type_with_no_settings_keeps_every_default(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types:\n  A: {}\n"))
    assert settings.types == (TypeView("A"),)
    assert settings.as_json()["types"] == [
        {"name": "A", "label": None, "columns": None, "page": None, "names": {}}
    ]


# Each setting, set.


@pytest.mark.parametrize("search", ["semantic", "text"])
def test_search_is_semantic_or_text(tmp_path: Path, search: str) -> None:
    assert read(_write(tmp_path, f"search: {search}\n")).search == search


@pytest.mark.parametrize("theme", ["auto", "light", "dark"])
def test_theme_is_auto_light_or_dark(tmp_path: Path, theme: str) -> None:
    assert read(_write(tmp_path, f"theme: {theme}\n")).theme == theme


def test_types_appear_in_the_order_the_file_writes_them(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types:\n  Zeta: {}\n  Alpha: {}\n  Mid: {}\n"))
    assert settings.types is not None
    assert [t.name for t in settings.types] == ["Zeta", "Alpha", "Mid"]
    assert [t["name"] for t in settings.as_json()["types"]] == ["Zeta", "Alpha", "Mid"]


def test_an_empty_types_mapping_lists_no_types(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types: {}\n"))
    assert settings.types == ()
    assert settings.as_json()["types"] == []


def test_a_type_sets_label_columns_page_and_names(tmp_path: Path) -> None:
    text = """\
types:
  Item:
    label: Thing
    columns: [b, a]
    page: [c, linked_to, a]
    names: {a: First, linked_to: Linked to}
"""
    settings = read(_write(tmp_path, text))
    assert settings.types == (
        TypeView(
            "Item",
            label="Thing",
            columns=("b", "a"),
            page=("c", "linked_to", "a"),
            names={"a": "First", "linked_to": "Linked to"},
        ),
    )
    assert settings.as_json()["types"] == [
        {
            "name": "Item",
            "label": "Thing",
            "columns": ["b", "a"],
            "page": ["c", "linked_to", "a"],
            "names": {"a": "First", "linked_to": "Linked to"},
        }
    ]


def test_empty_columns_and_page_show_none(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "types:\n  A: {columns: [], page: []}\n"))
    assert settings.types == (TypeView("A", columns=(), page=()),)


def test_export_types(tmp_path: Path) -> None:
    settings = read(_write(tmp_path, "export:\n  types: [B, A]\n"))
    assert settings.export_types == ("B", "A")
    assert settings.as_json()["export"] == {"types": ["B", "A"]}


def test_an_empty_export_mapping_keeps_its_default(tmp_path: Path) -> None:
    assert read(_write(tmp_path, "export: {}\n")).export_types is None


def test_the_settings_are_json_for_the_page() -> None:
    settings = from_json(
        {
            "search": "text",
            "theme": "dark",
            "types": {"A": {"label": "Ay", "columns": ["x"], "names": {"x": "Ex"}}},
            "export": {"types": ["A"]},
        }
    )
    data = settings.as_json()
    assert data == {
        "search": "text",
        "theme": "dark",
        "types": [
            {"name": "A", "label": "Ay", "columns": ["x"], "page": None, "names": {"x": "Ex"}}
        ],
        "export": {"types": ["A"]},
    }
    assert json.loads(json.dumps(data)) == data


# The shipped view files.


def _view_files() -> list[Path]:
    return [EXAMPLE, *sorted(FIXTURES.glob("*/view.yaml"))]


def test_every_fixture_has_a_view_file() -> None:
    fixtures = sorted(p.parent.name for p in FIXTURES.glob("*/pattern.yaml"))
    assert fixtures, "no fixture found"
    for name in fixtures:
        assert (FIXTURES / name / "view.yaml").is_file(), f"{name} has no view.yaml"


@pytest.mark.parametrize("path", _view_files(), ids=lambda p: p.parent.name + "/" + p.name)
def test_the_shipped_view_files_read_and_match_the_schema(path: Path) -> None:
    read(path)
    jsonschema.validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, _schema())


def test_the_example_sets_every_setting() -> None:
    settings = read(EXAMPLE)
    assert settings.types is not None and settings.export_types is not None
    first = settings.types[0]
    assert first.label is not None and first.columns is not None
    assert first.page is not None and dict(first.names)
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert {"search", "theme", "types", "export"} <= set(data)


def test_the_fixture_view_files_name_only_types_of_their_pattern() -> None:
    for view in sorted(FIXTURES.glob("*/view.yaml")):
        pattern = yaml.safe_load((view.parent / "pattern.yaml").read_text(encoding="utf-8"))
        settings = read(view)
        named = [t.name for t in settings.types or ()] + list(settings.export_types or ())
        assert set(named) <= set(pattern["types"]), view


def test_the_schema_is_a_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(_schema())


# Errors name the file, the line and the setting.

WRONG = [
    # (view file, line, setting named in the message)
    ("search: semantic\ncolour: red\n", 2, "colour"),
    ("search: fuzzy\n", 1, "search"),
    ("search: [text]\n", 1, "search"),
    ("theme: sepia\n", 1, "theme"),
    ("theme: true\n", 1, "theme"),
    ("types: [A, B]\n", 1, "types"),
    ("types:\n  A: {}\n  B: yes\n", 3, "types.B"),
    ("types:\n  A: {}\n  B:\n", 3, "types.B"),
    ("types:\n  A:\n    label: Ay\n    colour: red\n", 4, "types.A.colour"),
    ("types:\n  A:\n    label: 3\n", 3, "types.A.label"),
    ("types:\n  A:\n    label: ''\n", 3, "types.A.label"),
    ("types:\n  A:\n    columns: x\n", 3, "types.A.columns"),
    ("types:\n  A:\n    columns:\n      - x\n      - 2\n", 5, "types.A.columns"),
    ("types:\n  A:\n    columns: [x, x]\n", 3, "types.A.columns"),
    ("types:\n  A:\n    page: {x: 1}\n", 3, "types.A.page"),
    ("types:\n  A:\n    names: [x]\n", 3, "types.A.names"),
    ("types:\n  A:\n    names:\n      x: 1\n", 4, "types.A.names.x"),
    ('types:\n  "": {}\n', 2, "types"),
    ("export: [A]\n", 1, "export"),
    ("export:\n  types: A\n", 2, "export.types"),
    ("export:\n  carries: [A]\n", 2, "export.carries"),
    ("export:\n  types: [A, A]\n", 2, "export.types"),
    ("- search\n- text\n", 1, "view file"),
    ("just text\n", 1, "view file"),
]


@pytest.mark.parametrize(("text", "line", "setting"), WRONG)
def test_a_wrong_view_file_names_the_file_line_and_setting(
    tmp_path: Path, text: str, line: int, setting: str
) -> None:
    path = _write(tmp_path, text)
    with pytest.raises(ValueError) as e:
        read(path)
    message = str(e.value)
    assert message.startswith(f"{path}:{line}: "), message
    assert setting in message, message


@pytest.mark.parametrize(("text", "line", "setting"), WRONG)
def test_the_schema_refuses_each_wrong_view_file(text: str, line: int, setting: str) -> None:
    data = yaml.safe_load(text)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, _schema())


def test_a_duplicate_key_names_the_file_and_line(tmp_path: Path) -> None:
    path = _write(tmp_path, "search: text\ntheme: dark\nsearch: semantic\n")
    with pytest.raises(ValueError, match=rf"^{path}:3: .*duplicate"):
        read(path)


def test_a_file_that_is_not_yaml_names_the_file_and_line(tmp_path: Path) -> None:
    path = _write(tmp_path, "types:\n  A: {columns: [x\n")
    with pytest.raises(ValueError, match=rf"^{path}:\d+: "):
        read(path)


def test_a_file_that_is_not_utf8_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "view.yaml"
    path.write_bytes(b"search: \xff\n")
    with pytest.raises(ValueError, match=rf"^{path}: .*UTF-8"):
        read(path)


def test_a_missing_file_is_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read(tmp_path / "absent.yaml")


@pytest.mark.parametrize(
    "value",
    [
        {"search": "fuzzy"},
        {"types": {"A": {"columns": "x"}}},
        {"export": {"types": [1]}},
        ["search"],
    ],
)
def test_from_json_refuses_what_read_refuses(value: object) -> None:
    with pytest.raises(ValueError):
        from_json(value)
