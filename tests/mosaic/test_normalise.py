"""Normalisation steps of a canonical key (Specification 0.1, section 5.2; decision 8 on #14)."""

import pytest
from mosaic_build.mosaic.normalise import STEPS, WHITE_SPACE, normalise
from mosaic_format.schema import json_schema

from tests.spec.test_white_space import _spec_white_space


def test_white_space_is_the_25_code_points_the_spec_lists() -> None:
    assert {ord(c) for c in WHITE_SPACE} == _spec_white_space()


def test_every_step_the_pattern_schema_allows_is_implemented() -> None:
    allowed = json_schema("pattern")["$defs"]["normaliseStep"]["enum"]
    assert sorted(STEPS) == sorted(allowed)


def test_the_default_is_trim() -> None:
    assert normalise("  A b  ") == "A b"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\t\n\x0b\x0c\r X \x85\xa0", "X"),
        ("\u1680\u2000\u200a\u2028\u2029\u202f\u205f\u3000X\u3000", "X"),
        # Python's isspace adds U+001C-U+001F; they are not White_Space, so trim keeps them.
        ("\x1cX\x1f", "\x1cX\x1f"),
        # U+FEFF and U+200B are not White_Space either (JavaScript's \s has U+FEFF).
        ("\ufeffX\u200b", "\ufeffX\u200b"),
        (" in side ", "in side"),
    ],
)
def test_trim_removes_unicode_white_space_at_both_ends_only(text: str, expected: str) -> None:
    assert normalise(text, ["trim"]) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a\t \u3000b\x85\xa0c", "a b c"),
        ("  a  ", " a "),
        ("a\x1c\x1cb", "a\x1c\x1cb"),
    ],
)
def test_collapse_spaces_turns_each_run_of_white_space_into_one_space(
    text: str, expected: str
) -> None:
    assert normalise(text, ["collapse-spaces"]) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("temp-3x", "TEMP-3X"),
        ("straße", "STRAßE"),  # simple mapping: ß has no one-letter upper case
        ("ﬁ", "ﬁ"),  # the ligature's full mapping is "FI"; it has no simple one
        ("\u1f80", "\u1f88"),  # Greek with ypogegrammeni: its simple mapping is one letter
        ("ǆ", "Ǆ"),
        ("ŉ", "ŉ"),
    ],
)
def test_upper_uses_simple_case_mapping(text: str, expected: str) -> None:
    assert normalise(text, ["upper"]) == expected
    assert len(normalise(text, ["upper"])) == len(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("TEMP-3X", "temp-3x"),
        ("\u0130X", "ix"),  # full mapping gives "i̇" (two code points), simple gives "i"
        ("ΟΔΟΣ", "οδοσ"),  # no final-sigma context rule: one code point at a time
        ("Ǆ", "ǆ"),
    ],
)
def test_lower_uses_simple_case_mapping(text: str, expected: str) -> None:
    assert normalise(text, ["lower"]) == expected


def test_simple_case_mapping_never_changes_the_length() -> None:
    every = "".join(chr(c) for c in range(0x110000) if not 0xD800 <= c < 0xE000)
    assert len(normalise(every, ["upper"])) == len(every)
    assert len(normalise(every, ["lower"])) == len(every)


def test_dashes_and_underscores_swap() -> None:
    assert normalise("a-b_c", ["dash-to-underscore"]) == "a_b_c"
    assert normalise("a-b_c", ["underscore-to-dash"]) == "a-b-c"
    # Only U+002D is a dash; U+2010 and U+2212 are left alone.
    assert normalise("a\u2010b\u2212c", ["dash-to-underscore"]) == "a\u2010b\u2212c"


def test_steps_run_in_the_order_given() -> None:
    assert normalise(" a_b ", ["underscore-to-dash", "upper", "trim"]) == "A-B"
    assert normalise("a - b", ["collapse-spaces", "dash-to-underscore"]) == "a _ b"
    assert normalise("a - b", ["dash-to-underscore", "collapse-spaces"]) == "a _ b"
    # trim before collapse leaves no edge space; collapse before trim does too, but not after.
    assert normalise("  a  ", ["trim", "collapse-spaces"]) == "a"
    assert normalise("  a  ", ["collapse-spaces"]) == " a "


def test_no_steps_leaves_the_key_as_it_is() -> None:
    assert normalise("  a  ", []) == "  a  "
