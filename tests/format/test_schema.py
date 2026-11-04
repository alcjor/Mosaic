"""``mosaic_format.schema`` loads the five normative files (Spec 0.1, Status: Normative files).

From the repository (editable install) it falls back to ``<repo>/spec``; from a wheel it reads
the packaged copy (``tests/format/test_wheel.py``).
"""

import ast
import json

import pytest
from mosaic_format import NORMATIVE_FILES, schema

from tests.conftest import REPO, SPEC


def test_spec_dir_holds_the_five_files() -> None:
    names = {entry.name for entry in schema.spec_dir().iterdir()}
    assert set(NORMATIVE_FILES) <= names


@pytest.mark.parametrize("name", NORMATIVE_FILES)
def test_read_text_matches_the_repository(name: str) -> None:
    assert schema.read_text(name) == (SPEC / name).read_text(encoding="utf-8")


def test_format_sql_is_the_normative_schema() -> None:
    assert schema.format_sql() == (SPEC / "format.sql").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", schema.JSON_SCHEMAS)
def test_json_schema_loads(name: str) -> None:
    loaded = schema.json_schema(name)
    expected = json.loads((SPEC / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert loaded == expected
    assert loaded["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_json_schemas_are_the_four_of_the_spec() -> None:
    assert schema.JSON_SCHEMAS == ("pattern", "proposals", "build-report", "answers")
    assert {f"{n}.schema.json" for n in schema.JSON_SCHEMAS} | {"format.sql"} == set(
        NORMATIVE_FILES
    )


def test_unknown_names_are_refused() -> None:
    with pytest.raises(ValueError, match=r"notes\.txt"):
        schema.read_text("notes.txt")
    with pytest.raises(ValueError, match="grammar"):
        schema.json_schema("grammar")
    with pytest.raises(ValueError, match=r"\.\./format\.sql"):
        schema.read_text("../format.sql")


def test_build_hook_ships_the_same_files() -> None:
    # hatch_build.py cannot import the package at build time, so it keeps its own list.
    tree = ast.parse((REPO / "packages" / "mosaic-format" / "hatch_build.py").read_bytes())
    lists = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "NORMATIVE_FILES" for t in node.targets)
    ]
    assert lists == [NORMATIVE_FILES]
