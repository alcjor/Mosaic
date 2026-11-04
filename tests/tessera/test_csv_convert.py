"""The CSV tessera builder, value conversion (issue #13; Specification 0.1 sections 3.1, 3.4).

Conversions are declared per column in the settings, never guessed. ``date`` reads a value with
the given formats and writes ISO ``YYYY-MM-DD``; ``quantity`` splits a mixed field such as
``90 min`` into a number prop and a unit prop through a declared unit map; ``integer``,
``number`` and ``boolean`` (with explicit spellings) give JSON numbers and booleans. A value a
conversion cannot read stays as text, exactly as written, and is counted in the builder's
report. The kinds declared in ``type.props`` follow the conversions (section 3.4), and JSON
numbers are written in the canonical form of section 3.1. Nothing depends on the locale.
"""

import json
import locale
from collections.abc import Iterator, Mapping
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build.tessera.csv import (
    Boolean,
    Built,
    Conversion,
    Date,
    Integer,
    Number,
    Quantity,
    Settings,
    build,
)
from mosaic_format.check import check_file

UNITS = {"min": "min", "Season": "season", "Seasons": "season"}


def _csv(tmp_path: Path, column: str, values: list[str]) -> Path:
    """A CSV file with a key column ``k`` (1, 2, ...) and one more column of ``values``."""
    lines = [f"k,{column}"]
    for n, value in enumerate(values, start=1):
        quoted = '"' + value.replace('"', '""') + '"'
        lines.append(f"{n},{quoted}")
    path = tmp_path / "values.csv"
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def _settings(column: str, conversion: Conversion) -> Settings:
    return Settings(type="Item", key="k", props=(column,), convert={column: conversion})


def _props(out: Path) -> list[dict[str, object] | None]:
    with mosaic_format.open(out) as f:
        rows = f.query("SELECT props FROM node ORDER BY CAST(key AS INTEGER)")
    return [None if p is None else json.loads(str(p)) for (p,) in rows]


def _raw_props(out: Path) -> list[str | None]:
    with mosaic_format.open(out) as f:
        rows = f.query("SELECT props FROM node ORDER BY CAST(key AS INTEGER)")
    return [None if p is None else str(p) for (p,) in rows]


def _declared(out: Path) -> str:
    with mosaic_format.open(out) as f:
        ((props,),) = f.query("SELECT props FROM type")
    return str(props)


def _convert(
    tmp_path: Path, column: str, conversion: Conversion, values: list[str]
) -> tuple[Built, Path]:
    out = tmp_path / "values.tessera"
    built = build(_csv(tmp_path, column, values), out, _settings(column, conversion))
    return built, out


# --- date ------------------------------------------------------------------------------------


def test_a_date_is_written_as_iso_yyyy_mm_dd(tmp_path: Path) -> None:
    values = ["September 25, 2021", "August 4, 2017", "March 5, 2021", "May 31, 0999"]
    built, out = _convert(tmp_path, "added", Date(formats=("%B %d, %Y",)), values)
    assert _props(out) == [
        {"added": "2021-09-25"},
        {"added": "2017-08-04"},
        {"added": "2021-03-05"},
        {"added": "0999-05-31"},
    ]
    assert _declared(out) == '{"added":"text"}'
    assert built.report.unconverted == {"added": ()}


def test_date_formats_are_tried_in_the_order_given(tmp_path: Path) -> None:
    formats = ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%b %d %Y")
    values = ["03/04/2020", "12/31/2020", "2020-02-29", "Sep 1 2020"]
    _, out = _convert(tmp_path, "d", Date(formats=formats), values)
    assert _props(out) == [
        {"d": "2020-04-03"},  # day first, the first format that reads it
        {"d": "2020-12-31"},  # no 31st month: the second format reads it
        {"d": "2020-02-29"},
        {"d": "2020-09-01"},
    ]


def test_month_names_are_english_in_any_letter_case(tmp_path: Path) -> None:
    values = ["SEPTEMBER 5, 2021", "june 1, 2020", "Dec 24, 2019", "dec 25, 2019"]
    _, out = _convert(tmp_path, "d", Date(formats=("%B %d, %Y", "%b %d, %Y")), values)
    assert _props(out) == [
        {"d": "2021-09-05"},
        {"d": "2020-06-01"},
        {"d": "2019-12-24"},
        {"d": "2019-12-25"},
    ]


def test_surrounding_white_space_does_not_stop_a_conversion(tmp_path: Path) -> None:
    _, out = _convert(tmp_path, "d", Date(formats=("%B %d, %Y",)), [" August 4, 2017 "])
    assert _props(out) == [{"d": "2017-08-04"}]


def test_a_percent_sign_in_a_format_is_written_twice(tmp_path: Path) -> None:
    _, out = _convert(tmp_path, "d", Date(formats=("%Y%%%m%%%d",)), ["2020%1%2"])
    assert _props(out) == [{"d": "2020-01-02"}]


@pytest.mark.parametrize(
    "value",
    [
        "Septober 5, 2021",  # no such month
        "February 30, 2021",  # no such day
        "February 29, 2021",  # not a leap year
        "September 0, 2021",
        "September 5 2021",  # the comma is part of the format
        "September 5, 21",  # %Y is four digits
        "September 123, 2021",
        "2021-09-05",
        "September 5, 2021 extra",
        "September \uff15, 2021",  # only ASCII digits are digits
        "März 5, 2021",  # month names are English
    ],
)
def test_a_value_no_date_format_reads_stays_as_text_and_is_counted(
    tmp_path: Path, value: str
) -> None:
    values = ["May 1, 2020", value, "June 2, 2020"]
    built, out = _convert(tmp_path, "d", Date(formats=("%B %d, %Y",)), values)
    assert _props(out) == [{"d": "2020-05-01"}, {"d": value}, {"d": "2020-06-02"}]
    assert built.report.unconverted == {"d": (2,)}


def test_an_unconverted_value_keeps_its_white_space(tmp_path: Path) -> None:
    built, out = _convert(tmp_path, "d", Date(formats=("%Y-%m-%d",)), ["  soon "])
    assert _props(out) == [{"d": "  soon "}]
    assert built.report.unconverted == {"d": (1,)}


def test_an_empty_cell_makes_no_prop_and_is_not_counted(tmp_path: Path) -> None:
    built, out = _convert(tmp_path, "d", Date(formats=("%Y-%m-%d",)), ["", "2020-01-01"])
    assert _props(out) == [None, {"d": "2020-01-01"}]
    assert built.report.unconverted == {"d": ()}


@pytest.mark.parametrize(
    ("formats", "message"),
    [
        ((), r"column 'd'.*at least one format"),
        (("%m %d",), r"'%m %d'.*%Y"),
        (("%Y %d",), r"'%Y %d'.*%m or %B or %b"),
        (("%Y %m",), r"'%Y %m'.*%d"),
        (("%Y %m %d %Y",), r"'%Y %m %d %Y'.*twice"),
        (("%Y %B %m %d",), r"twice"),
        (("%Y-%m-%d %H",), r"'%H'"),
        (("%Y-%m-%d%",), r"ends in '%'"),
    ],
)
def test_bad_date_formats_are_refused(
    tmp_path: Path, formats: tuple[str, ...], message: str
) -> None:
    out = tmp_path / "x.tessera"
    with pytest.raises(ValueError, match=message):
        build(_csv(tmp_path, "d", ["2020-01-01"]), out, _settings("d", Date(formats=formats)))
    assert not out.exists()


# --- quantity --------------------------------------------------------------------------------


def test_a_quantity_is_split_into_a_number_and_a_unit(tmp_path: Path) -> None:
    conversion = Quantity(number="duration", unit="duration_unit", units=UNITS)
    values = ["90 min", "2 Seasons", "1 Season", "1.5 min", "45min", " 3  Seasons "]
    built, out = _convert(tmp_path, "duration", conversion, values)
    assert _props(out) == [
        {"duration": 90, "duration_unit": "min"},
        {"duration": 2, "duration_unit": "season"},
        {"duration": 1, "duration_unit": "season"},
        {"duration": 1.5, "duration_unit": "min"},
        {"duration": 45, "duration_unit": "min"},
        {"duration": 3, "duration_unit": "season"},
    ]
    assert _raw_props(out)[0] == '{"duration":90,"duration_unit":"min"}'
    assert _declared(out) == '{"duration":"number","duration_unit":"text"}'
    assert built.report.unconverted == {"duration": ()}


def test_the_number_and_unit_props_may_have_any_declared_names(tmp_path: Path) -> None:
    conversion = Quantity(number="length", unit="unit", units=UNITS)
    _, out = _convert(tmp_path, "duration", conversion, ["90 min"])
    assert _props(out) == [{"length": 90, "unit": "min"}]
    assert _declared(out) == '{"length":"number","unit":"text"}'


def test_a_unit_map_entry_for_the_empty_spelling_reads_a_bare_number(tmp_path: Path) -> None:
    conversion = Quantity(number="n", unit="u", units={"": "piece", "pcs": "piece"})
    _, out = _convert(tmp_path, "c", conversion, ["12", "3 pcs"])
    assert _props(out) == [{"n": 12, "u": "piece"}, {"n": 3, "u": "piece"}]


@pytest.mark.parametrize(
    "value",
    ["3 parts", "90", "min", "90 MIN", "ninety min", "90 min 2 Seasons", "1,5 min", "- 3 min"],
)
def test_a_quantity_that_cannot_be_read_stays_as_text_in_the_number_prop(
    tmp_path: Path, value: str
) -> None:
    conversion = Quantity(number="duration", unit="duration_unit", units=UNITS)
    built, out = _convert(tmp_path, "duration", conversion, ["90 min", value])
    assert _props(out) == [{"duration": 90, "duration_unit": "min"}, {"duration": value}]
    assert built.report.unconverted == {"duration": (2,)}


@pytest.mark.parametrize(
    ("conversion", "props", "message"),
    [
        (Quantity(number="n", unit="n", units=UNITS), ("q",), r"'n'.*twice"),
        (Quantity(number="other", unit="u", units=UNITS), ("q", "other"), r"'other'.*twice"),
        (Quantity(number="n", unit="other", units=UNITS), ("q", "other"), r"'other'.*twice"),
        (Quantity(number="n", unit="u", units={}), ("q",), r"column 'q'.*unit map"),
        (Quantity(number="n", unit="u", units={"m": ""}), ("q",), r"'m'.*empty"),
        (Quantity(number="", unit="u", units=UNITS), ("q",), r"prop name"),
        (Quantity(number="n", unit=" u", units=UNITS), ("q",), r"prop name"),
    ],
)
def test_bad_quantity_settings_are_refused(
    tmp_path: Path, conversion: Quantity, props: tuple[str, ...], message: str
) -> None:
    path = tmp_path / "q.csv"
    path.write_bytes(b"k,q,other\n1,2 min,x\n")
    settings = Settings(type="Item", key="k", props=props, convert={"q": conversion})
    out = tmp_path / "x.tessera"
    with pytest.raises(ValueError, match=message):
        build(path, out, settings)
    assert not out.exists()


# --- integer and number ----------------------------------------------------------------------


def test_integers_are_json_integers(tmp_path: Path) -> None:
    values = ["42", "-7", "+3", " 12 ", "007", "-0", "9007199254740991", "-9007199254740991"]
    built, out = _convert(tmp_path, "n", Integer(), values)
    assert _raw_props(out) == [
        '{"n":42}',
        '{"n":-7}',
        '{"n":3}',
        '{"n":12}',
        '{"n":7}',
        '{"n":0}',
        '{"n":9007199254740991}',
        '{"n":-9007199254740991}',
    ]
    assert _declared(out) == '{"n":"integer"}'
    assert built.report.unconverted == {"n": ()}


@pytest.mark.parametrize(
    "value",
    [
        *("4.0", "1e3", "x", "1 000", "1,000", "0x10", "\u0663"),
        *("9007199254740992", "-9007199254740992"),
    ],
)
def test_a_value_that_is_not_a_safe_integer_stays_as_text(tmp_path: Path, value: str) -> None:
    built, out = _convert(tmp_path, "n", Integer(), [value])
    assert _props(out) == [{"n": value}]
    assert built.report.unconverted == {"n": (1,)}


def test_numbers_are_json_numbers_in_canonical_form(tmp_path: Path) -> None:
    values = ["3.5", "-0.25", "1e3", ".5", "5.", "1.50", "+2", "1E-7", "1e21", "9007199254740991.0"]
    built, out = _convert(tmp_path, "x", Number(), values)
    assert _raw_props(out) == [
        '{"x":3.5}',
        '{"x":-0.25}',
        '{"x":1000}',
        '{"x":0.5}',
        '{"x":5}',
        '{"x":1.5}',
        '{"x":2}',
        '{"x":1e-7}',
        '{"x":1e+21}',
        '{"x":9007199254740991}',
    ]
    assert _declared(out) == '{"x":"number"}'
    assert built.report.unconverted == {"x": ()}


@pytest.mark.parametrize(
    "value",
    [
        *("1,5", "nan", "NaN", "inf", "-Infinity", "1e999", "0x10", "\u0661", "1_000", "e3", "."),
        # Written as an integer outside +/-(2**53 - 1), which is stored as a string (3.1).
        *("9007199254740992", "-9007199254740993.0", "123456789012345678901", "9.99e20"),
    ],
)
def test_a_value_that_is_not_a_finite_decimal_number_stays_as_text(
    tmp_path: Path, value: str
) -> None:
    built, out = _convert(tmp_path, "x", Number(), [value])
    assert _props(out) == [{"x": value}]
    assert built.report.unconverted == {"x": (1,)}


# --- boolean ---------------------------------------------------------------------------------


def test_booleans_use_only_the_spellings_declared(tmp_path: Path) -> None:
    conversion = Boolean(true=("yes", "Y"), false=("no", "N"))
    built, out = _convert(tmp_path, "b", conversion, ["yes", "N", "Y", " no ", "Yes", "true"])
    assert _raw_props(out) == [
        '{"b":true}',
        '{"b":false}',
        '{"b":true}',
        '{"b":false}',
        '{"b":"Yes"}',  # spellings are compared exactly
        '{"b":"true"}',  # nothing is assumed
    ]
    assert _declared(out) == '{"b":"boolean"}'
    assert built.report.unconverted == {"b": (5, 6)}


@pytest.mark.parametrize(
    ("conversion", "message"),
    [
        (Boolean(true=(), false=("no",)), r"column 'b'.*true spelling"),
        (Boolean(true=("yes",), false=()), r"column 'b'.*false spelling"),
        (Boolean(true=("yes", "x"), false=("x",)), r"'x'.*both true and false"),
        (Boolean(true=("",), false=("no",)), r"empty"),
        (Boolean(true=(" yes",), false=("no",)), r"' yes'.*white space"),
    ],
)
def test_bad_boolean_spellings_are_refused(
    tmp_path: Path, conversion: Boolean, message: str
) -> None:
    out = tmp_path / "x.tessera"
    with pytest.raises(ValueError, match=message):
        build(_csv(tmp_path, "b", ["yes"]), out, _settings("b", conversion))
    assert not out.exists()


# --- settings and report ---------------------------------------------------------------------


def test_a_conversion_for_a_column_that_is_not_a_prop_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    path.write_bytes(b"k,a,b\n1,2,3\n")
    settings = Settings(key="k", props=("a",), convert={"b": Integer()})
    with pytest.raises(ValueError, match=r"convert.*column 'b'.*not in props"):
        build(path, tmp_path / "x.tessera", settings)


def test_columns_without_a_conversion_stay_text(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    path.write_bytes(b"k,a,b\n1,2,3\n")
    out = tmp_path / "v.tessera"
    built = build(path, out, Settings(key="k", props=("a", "b"), convert={"b": Integer()}))
    assert _raw_props(out) == ['{"a":"2","b":3}']
    assert _declared(out) == '{"a":"text","b":"integer"}'
    assert built.report.unconverted == {"b": ()}


def test_the_conversions_are_recorded_in_the_header_settings(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    path.write_bytes(b"k,d,q,i,x,b\n1,2020-01-01,2 min,1,1.5,y\n")
    convert: Mapping[str, Conversion] = {
        "q": Quantity(number="n", unit="u", units={"min": "min", "h": "hour"}),
        "d": Date(formats=("%Y-%m-%d", "%B %d, %Y")),
        "i": Integer(),
        "x": Number(),
        "b": Boolean(true=("y",), false=("n", "no")),
    }
    settings = Settings(key="k", props=("d", "q", "i", "x", "b"), convert=convert)
    out = tmp_path / "v.tessera"
    build(path, out, settings)
    with mosaic_format.open(out) as f:
        ((text,),) = f.query("SELECT settings FROM header")
    value = json.loads(str(text))
    assert value["convert"] == {
        "b": {"kind": "boolean", "true": ["y"], "false": ["n", "no"]},
        "d": {"kind": "date", "formats": ["%Y-%m-%d", "%B %d, %Y"]},
        "i": {"kind": "integer"},
        "q": {"kind": "quantity", "number": "n", "unit": "u", "units": {"h": "hour", "min": "min"}},
        "x": {"kind": "number"},
    }
    assert text == json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert _raw_props(out) == ['{"b":true,"d":"2020-01-01","i":1,"n":2,"u":"min","x":1.5}']
    assert _declared(out) == (
        '{"b":"boolean","d":"text","i":"integer","n":"number","u":"text","x":"number"}'
    )
    assert list(check_file(out).violations) == []


def test_the_report_lists_unconverted_rows_per_converted_column(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    path.write_bytes(b"k,i,x,t\n1,1,a,t\n2,b,2,t\n3,c,,t\n4,4,d,t\n")
    settings = Settings(key="k", props=("x", "i", "t"), convert={"x": Number(), "i": Integer()})
    built = build(path, tmp_path / "v.tessera", settings)
    assert built.report.unconverted == {"i": (2, 3), "x": (1, 4)}
    assert list(built.report.unconverted) == ["i", "x"]
    assert built.report.counts() == {"i": 2, "x": 2}


def test_a_build_without_conversions_reports_nothing(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    path.write_bytes(b"k,a\n1,2\n")
    built = build(path, tmp_path / "v.tessera", Settings(key="k", props=("a",)))
    assert built.report.unconverted == {}


def test_the_result_is_still_the_sealed_file(tmp_path: Path) -> None:
    built, out = _convert(tmp_path, "n", Integer(), ["1"])
    with mosaic_format.open(out) as f:
        assert built.knowledge_hash == f.knowledge_hash
    assert built.path == out


# --- no dependence on the locale -------------------------------------------------------------

LOCALE_VALUES = {
    "d": ["March 5, 2021", "May 6, 2021", "December 7, 2021", "Mär 5, 2021"],
    "x": ["1.5", "1,5", "2", "1e3"],
}


@pytest.fixture
def german_locale() -> Iterator[str]:
    """LC_ALL set to a German locale for the test, if the system has one."""
    saved = locale.setlocale(locale.LC_ALL)
    for name in ("de_DE.UTF-8", "de_DE.utf8", "de_DE"):
        try:
            locale.setlocale(locale.LC_ALL, name)
        except locale.Error:
            continue
        try:
            yield name
        finally:
            locale.setlocale(locale.LC_ALL, saved)
        return
    pytest.skip("no de_DE locale on this system")


def _locale_build(tmp_path: Path, name: str) -> tuple[Built, Path]:
    path = tmp_path / "v.csv"
    rows = zip(LOCALE_VALUES["d"], LOCALE_VALUES["x"], strict=True)
    lines = ["k,d,x", *(f'{n},"{d}","{x}"' for n, (d, x) in enumerate(rows, start=1))]
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    settings = Settings(
        key="k",
        props=("d", "x"),
        convert={"d": Date(formats=("%B %d, %Y", "%b %d, %Y")), "x": Number()},
    )
    out = tmp_path / f"{name}.tessera"
    return build(path, out, settings), out


def test_conversions_do_not_depend_on_the_locale(tmp_path: Path, german_locale: str) -> None:
    """Done when (#13): run under LC_ALL=de_DE when the system has it."""
    built, out = _locale_build(tmp_path, "german")
    assert _props(out) == [
        {"d": "2021-03-05", "x": 1.5},
        {"d": "2021-05-06", "x": "1,5"},
        {"d": "2021-12-07", "x": 2},
        {"d": "Mär 5, 2021", "x": 1000},
    ]
    assert built.report.unconverted == {"d": (4,), "x": (2,)}
    locale.setlocale(locale.LC_ALL, "C")
    again, _ = _locale_build(tmp_path, "c")
    assert again.knowledge_hash == built.knowledge_hash
