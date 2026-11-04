"""Canonical JSON text: RFC 8785 and I-JSON (section 3.1, decision on #59).

Expected number strings are ECMAScript ``String(x)`` for each double, generated with Bun from
the bit patterns of RFC 8785 Appendix B, so they test against the standard, not this code.
"""

import struct

import pytest
from mosaic_format.canonical_json import canonical_json

# RFC 8785 Appendix B: IEEE 754 bit pattern -> ECMAScript Number::toString.
RFC_8785_NUMBERS = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
]


@pytest.mark.parametrize(("bits", "expected"), RFC_8785_NUMBERS)
def test_numbers_follow_rfc_8785_appendix_b(bits: str, expected: str) -> None:
    (x,) = struct.unpack(">d", bytes.fromhex(bits))
    assert canonical_json(f"[{x!r}]") == f"[{expected}]"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("90", "90"),
        ("90.0", "90"),
        ("1e-7", "1e-7"),
        ("0.1", "0.1"),
        ("1e21", "1e+21"),
        ("1e20", "100000000000000000000"),
        ("-0.0", "0"),
        ("2.5e-7", "2.5e-7"),
        ("3.0e2", "300"),
        ("1E+30", "1e+30"),
        ("9007199254740991", "9007199254740991"),
        ("-9007199254740991", "-9007199254740991"),
    ],
)
def test_number_spellings(text: str, expected: str) -> None:
    assert canonical_json(f"[{text}]") == f"[{expected}]"


def test_keys_sort_by_utf16_code_units_not_utf8_bytes() -> None:
    """U+1F600 is a surrogate pair (0xD83D...), so it sorts before U+FB33 in UTF-16 order."""
    text = '{"\\u20ac":1,"\\r":2,"\\ufb33":3,"1":4,"\\ud83d\\ude00":5,"\\u0080":6,"\\u00f6":7}'
    expected = '{"\\r":2,"1":4,"\u0080":6,"\u00f6":7,"\u20ac":1,"\U0001f600":5,"\ufb33":3}'
    assert canonical_json(text) == expected


def test_strings_escape_only_what_json_requires() -> None:
    text = '"a\\u0000\\u001f\\u007f\\"\\\\\\/\\b\\f\\n\\r\\t\\u2028\\u00e9\\ud83d\\ude00"'
    expected = '"a\\u0000\\u001f\x7f\\"\\\\/\\b\\f\\n\\r\\t\u2028\u00e9\U0001f600"'
    assert canonical_json(text) == expected


def test_whitespace_goes_and_nesting_is_kept() -> None:
    text = ' { "b" : [ 1 , { "y" : true , "x" : null } ] , "a" : "s" } '
    assert canonical_json(text) == '{"a":"s","b":[1,{"x":null,"y":true}]}'


@pytest.mark.parametrize(
    "text",
    [
        '{"a":1,"b":[2,3]}',
        '["' + "b" * 64 + '","' + "a" * 64 + '"]',
        '{"note":"a\\u0000b","n":-0.5,"big":"12345678901234567890"}',
        "[]",
        "{}",
    ],
)
def test_canonical_text_is_a_fixed_point(text: str) -> None:
    once = canonical_json(text)
    assert canonical_json(once) == once


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ('{"a":1,"a":2}', "duplicate object key"),
        ("[NaN]", "NaN"),
        ("[Infinity]", "Infinity"),
        ("[-Infinity]", "-Infinity"),
        ("[1e400]", "outside the range"),
        ("[9007199254740992]", "store it as a string"),
        ("[-9007199254740992]", "store it as a string"),
        ('{"id":12345678901234567890}', "store it as a string"),
        ('["\\ud800"]', "unpaired surrogate"),
        ('{"\\udc00":1,"a":2}', "unpaired surrogate"),
        ("{'a':1}", "not JSON"),
        ("", "not JSON"),
    ],
)
def test_refuses_what_is_not_i_json(text: str, words: str) -> None:
    with pytest.raises(ValueError, match=words):
        canonical_json(text)
