"""Patterns and proposals are read as YAML 1.2 core schema and duplicate keys are rejected.

Spec 0.1 section 5: "Both are read as YAML 1.2 core schema; a reader MUST reject duplicate
keys." The values below are the core schema's (YAML 1.2.2, section 10.3): ``yes`` and ``on``
are text, ``017`` is seventeen, a date is text, and only the core tags exist.
"""

import math

import pytest
from mosaic_format.yaml_core import YamlError, load


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("yes", "yes"),
        ("no", "no"),
        ("on", "on"),
        ("off", "off"),
        ("y", "y"),
        ("true", True),
        ("True", True),
        ("FALSE", False),
        ("null", None),
        ("~", None),
        ("", None),
        ("017", 17),
        ("0o17", 15),
        ("0x1F", 31),
        ("-3", -3),
        ("+3", 3),
        ("1_000", "1_000"),
        ("0b101", "0b101"),
        ("1.5", 1.5),
        ("1e3", 1000.0),
        (".5", 0.5),
        ("-.inf", -math.inf),
        ("2026-11-01", "2026-11-01"),
        ("12:30:00", "12:30:00"),
        ("'017'", "017"),
        ('"true"', "true"),
        ("!!str 12", "12"),
        ("!!int '12'", 12),
        ("!!float 1", 1.0),
        ("! 12", "12"),
    ],
)
def test_scalars_follow_the_core_schema(text: str, value: object) -> None:
    loaded = load(f"v: {text}\n", "f.yaml").data
    assert loaded == {"v": value}
    assert type(loaded["v"]) is type(value)


def test_nan_is_a_float() -> None:
    assert math.isnan(load("v: .nan\n", "f.yaml").data["v"])


def test_block_scalars_and_collections() -> None:
    doc = load("a: [1, two]\nb: {c: d}\ne: |\n  line\n", "f.yaml").data
    assert doc == {"a": [1, "two"], "b": {"c": "d"}, "e": "line\n"}


def test_merge_keys_are_ordinary_keys() -> None:
    # `<<` is a YAML 1.1 type; the 1.2 core schema has none, so it is just a key.
    assert load("<<: {a: 1}\nb: 2\n", "f.yaml").data == {"<<": {"a": 1}, "b": 2}


def test_aliases_repeat_the_anchored_value() -> None:
    assert load("a: &x [1, 2]\nb: *x\n", "f.yaml").data == {"a": [1, 2], "b": [1, 2]}


def test_an_anchored_key_can_be_repeated_as_a_value() -> None:
    assert load("&k a: 1\nb: *k\n", "f.yaml").data == {"a": 1, "b": "a"}


def _error(text: str) -> YamlError:
    with pytest.raises(YamlError) as caught:
        load(text, "where/f.yaml")
    assert "where/f.yaml" in str(caught.value)
    return caught.value


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("a: 1\na: 2\n", 2),
        ("a:\n  b: 1\n  c: 2\n  b: 3\n", 4),
        ("- {x: 1, x: 2}\n", 1),
        ("a: 1\n'a': 2\n", 2),
        ("? a\n: 1\na: 2\n", 3),
    ],
)
def test_duplicate_keys_are_rejected(text: str, line: int) -> None:
    error = _error(text)
    assert error.rule == "duplicate-key"
    assert error.line == line
    assert "duplicate key" in str(error)


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("a: [1\n", "YAML"),
        ("a: !!binary aGk=\n", "tag"),
        ("a: !custom x\n", "tag"),
        ("a: !!int x\n", "!!int"),
        ("a: !!timestamp 2026-11-01\n", "tag"),
        ("1: a\n", "text"),
        ("null: a\n", "text"),
        ("[a]: b\n", "text"),
        ("a: 1\n---\nb: 2\n", "one document"),
        ("%YAML 1.1\n---\na: yes\n", "1.1"),
        ("a: *missing\n", "YAML"),
    ],
)
def test_other_yaml_is_rejected(text: str, needle: str) -> None:
    error = _error(text)
    assert error.rule == "yaml"
    assert needle in str(error)


def test_alias_expansion_is_bounded() -> None:
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    lines += [f"a{i}: &a{i} [{', '.join([f'*a{i - 1}'] * 10)}]" for i in range(1, 9)]
    error = _error("\n".join(lines) + "\n")
    assert error.rule == "yaml"
    assert "too large" in str(error)


@pytest.mark.parametrize(
    "number",
    ["1" * 5000, "0x" + "f" * 5000, "0o" + "7" * 5000, "1." + "5" * 5000, "!!int " + "1" * 5000],
)
def test_overlong_numbers_are_rejected(number: str) -> None:
    error = _error(f"v: {number}\n")
    assert error.rule == "yaml"
    assert "more than 1000 characters" in str(error)


def test_long_text_that_is_not_a_number_is_kept() -> None:
    assert load(f"v: {'1' * 5000}x\n", "f.yaml").data == {"v": "1" * 5000 + "x"}
    assert load(f"v: '{'1' * 5000}'\n", "f.yaml").data == {"v": "1" * 5000}


def _alias_chain(links: int) -> str:
    """Each anchor wraps the one before: two levels deep in the text, ``links + 1`` in the data."""
    lines = ["- &a0 [x]"] + [f"- &a{k} [*a{k - 1}]" for k in range(1, links + 1)]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    "text",
    [
        "[" * 2000,
        "[" * 65 + "]" * 65 + "\n",
        "a: " + "[" * 64 + "]" * 64 + "\n",
        _alias_chain(400),
        _alias_chain(63),
        "a: &x " + "[" * 40 + "]" * 40 + "\nb: " + "[" * 24 + "*x" + "]" * 24 + "\n",
    ],
    ids=["2000", "65", "64 under a key", "alias chain 400", "alias chain 63", "alias in deep"],
)
def test_deep_nesting_is_rejected(text: str) -> None:
    error = _error(text)
    assert error.rule == "yaml"
    assert "nested more than 64 levels" in str(error)


def test_nesting_up_to_the_limit_is_read() -> None:
    assert load("[" * 64 + "]" * 64 + "\n", "f.yaml").data is not None
    assert load("a: " + "[" * 63 + "]" * 63 + "\n", "f.yaml").data is not None
    # The outer sequence and 63 nested lists: 64 levels.
    data = load(_alias_chain(62), "f.yaml").data
    inner, levels = data, 0
    while isinstance(inner, list):
        inner, levels = inner[-1], levels + 1
    assert (inner, levels) == ("x", 64)


def test_an_empty_file_is_null() -> None:
    assert load("", "f.yaml").data is None
    assert load("# only a comment\n", "f.yaml").data is None


def test_lines_are_kept_for_every_key_and_item() -> None:
    doc = load("a:\n  b:\n    - x\n    - y\nc: 1\n", "f.yaml")
    assert doc.line(()) == 1
    assert doc.line(("a",)) == 1
    assert doc.line(("a", "b")) == 2
    assert doc.line(("a", "b", 1)) == 4
    assert doc.line(("c",)) == 5
    # An unknown path falls back to its nearest known parent.
    assert doc.line(("a", "b", 1, "z")) == 4
