"""A CSV tessera's settings file: the shape of ``header.settings`` (issue #18)."""

import json
from pathlib import Path

import pytest
from mosaic_build.tessera.csv import Boolean, Date, Integer, Number, Quantity, Settings
from mosaic_build.tessera.settings import from_json, read

EVERY_KIND = Settings(
    type="Item",
    key="id",
    label="name",
    summary="note",
    props=("made", "length", "count", "weight", "open"),
    encoding="latin-1",
    delimiter="\t",
    convert={
        "made": Date(("%Y-%m-%d", "%d %B %Y")),
        "length": Quantity(number="length", unit="length_unit", units={"min": "minute", "": "x"}),
        "count": Integer(),
        "weight": Number(),
        "open": Boolean(true=("yes", "Y"), false=("no",)),
    },
)


def test_every_setting_and_conversion_round_trips_through_header_settings() -> None:
    assert from_json(json.loads(EVERY_KIND.as_json())) == EVERY_KIND


def test_a_yaml_settings_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        """\
type: Item
key: id
label: name
summary: note
props: [made, length, count, weight, open]
encoding: latin-1
delimiter: "\\t"
convert:
  made: {kind: date, formats: ["%Y-%m-%d", "%d %B %Y"]}
  length:
    kind: quantity
    number: length
    unit: length_unit
    units: {min: minute, "": x}
  count: {kind: integer}
  weight: {kind: number}
  open: {kind: boolean, "true": ["yes", "Y"], "false": ["no"]}
""",
        encoding="utf-8",
    )
    assert read(path) == EVERY_KIND


def test_an_empty_mapping_is_the_default_settings() -> None:
    assert from_json({}) == Settings()


@pytest.mark.parametrize(
    ("text", "line", "named"),
    [
        ("type: Item\nconvert:\n  a: {kind: date, formats: x}\nprops: [a]\n", 3, "formats"),
        ("props: [a]\nconvert: {a: {kind: quantity, number: n, unit: u}}\n", 2, "units"),
        ('props: [a]\nconvert: {a: {kind: boolean, "true": [y], "false": n}}\n', 2, "false"),
        ("type: item\n", None, "type"),
        ("props: [a]\nconvert: {b: {kind: integer}}\n", None, "'b'"),
    ],
)
def test_refusals_name_the_file_line_and_setting(
    tmp_path: Path, text: str, line: int | None, named: str
) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as e:
        read(path)
    message = str(e.value)
    assert message.startswith(f"{path}:{line}:" if line is not None else f"{path}:")
    assert named in message


def test_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_bytes(b"type: \xff\n")
    with pytest.raises(ValueError, match="not UTF-8"):
        read(path)
