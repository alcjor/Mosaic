"""Value conversions for table tessera builders (issue #13; Specification 0.1 sections 3.1, 3.4).

A conversion is declared per column, never guessed. It reads one cell of its column and gives
the props the cell stands for, or None when it cannot read the value; the builder then keeps
the value as text. White space around a value is ignored. Conversions read no locale: month
names are English (any letter case) and digits are ASCII ``0`` to ``9``.

- ``Date(formats)``: the formats are tried in order and the first that reads the whole value
  gives ISO ``YYYY-MM-DD``. A format holds ``%Y`` (four digits), ``%m`` (one or two digits) or
  ``%B`` (full month name) or ``%b`` (three-letter month name), and ``%d`` (one or two digits),
  each exactly once; ``%%`` is a percent sign and every other character matches itself. Dates
  that do not exist, such as 30 February, are not read. Declared kind ``text``.
- ``Quantity(number, unit, units)``: a decimal number, optional white space and a unit spelling
  that ``units`` maps to the unit written. The number goes to the prop ``number`` (kind
  ``number``), the mapped unit to the prop ``unit`` (kind ``text``). An entry for the empty
  spelling reads a bare number. An unread value stays as text in the prop ``number``.
- ``Integer()``: an optional sign and ASCII digits, within +/-(2**53 - 1) (section 3.1: larger
  integers would change value). Declared kind ``integer``.
- ``Number()``: a decimal number with optional sign, fraction and exponent that is a finite
  double; not an integer beyond +/-(2**53 - 1) written without exponent, which section 3.1
  stores as a string. Declared kind ``number``.
- ``Boolean(true, false)``: the value is one of the spellings given, compared exactly.
  Declared kind ``boolean``.
"""

import functools
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from mosaic_format.canonical_json import MAX_SAFE_INTEGER

INTEGER = re.compile(r"[+-]?[0-9]+")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
QUANTITY = re.compile(rf"({NUMBER.pattern})\s*(.*)", re.DOTALL)

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
"""English month names, written out: ``calendar`` and ``strptime`` follow the locale."""
MONTH_NUMBERS = {m.lower(): n for n, m in enumerate(MONTHS, start=1)}
MONTH_NUMBERS.update({m[:3].lower(): n for n, m in enumerate(MONTHS, start=1)})

_DIRECTIVES = {
    "Y": ("year", "[0-9]{4}"),
    "m": ("month", "[0-9]{1,2}"),
    "B": ("month", "(?i:" + "|".join(MONTHS) + ")"),
    "b": ("month", "(?i:" + "|".join(m[:3] for m in MONTHS) + ")"),
    "d": ("day", "[0-9]{1,2}"),
}


def _number(text: str) -> float | None:
    """The double ``text`` writes, or None when it is not one a file can hold as a number.

    A double that is an integer beyond +/-(2**53 - 1) and below 1e21 is written in canonical
    form as an integer, and such integers are stored as strings (section 3.1).
    """
    if NUMBER.fullmatch(text) is None:
        return None
    x = float(text)
    if not math.isfinite(x):
        return None
    if x.is_integer() and MAX_SAFE_INTEGER < abs(x) < 1e21:
        return None
    return x


@functools.cache
def _compile(column: str, fmt: str) -> re.Pattern[str]:
    """A date format as a regular expression with groups ``year``, ``month`` and ``day``."""
    parts: list[str] = []
    seen: set[str] = set()
    i = 0
    while i < len(fmt):
        c = fmt[i]
        if c != "%":
            parts.append(re.escape(c))
            i += 1
            continue
        if i + 1 == len(fmt):
            raise ValueError(f"settings: column {column!r}: date format {fmt!r} ends in '%'")
        d = fmt[i + 1]
        i += 2
        if d == "%":
            parts.append("%")
            continue
        if d not in _DIRECTIVES:
            raise ValueError(
                f"settings: column {column!r}: date format {fmt!r} has '%{d}'; "
                f"only %Y, %m, %B, %b, %d and %% are read"
            )
        group, pattern = _DIRECTIVES[d]
        if group in seen:
            raise ValueError(
                f"settings: column {column!r}: date format {fmt!r} gives the {group} twice"
            )
        seen.add(group)
        parts.append(f"(?P<{group}>{pattern})")
    for group, directive in (("year", "%Y"), ("month", "%m or %B or %b"), ("day", "%d")):
        if group not in seen:
            raise ValueError(f"settings: column {column!r}: date format {fmt!r} has no {directive}")
    return re.compile("".join(parts), re.ASCII | re.DOTALL)


@dataclass(frozen=True)
class Date:
    """Read a date with the given formats, in order, and write ISO ``YYYY-MM-DD``."""

    formats: tuple[str, ...]

    def check(self, column: str) -> None:
        if not self.formats:
            raise ValueError(f"settings: column {column!r}: a date needs at least one format")
        for fmt in self.formats:
            _compile(column, fmt)

    def as_json(self) -> dict[str, object]:
        return {"kind": "date", "formats": list(self.formats)}

    def kinds(self, column: str) -> dict[str, str]:
        return {column: "text"}

    def fallback(self, column: str) -> str:
        return column

    def read(self, column: str, cell: str) -> dict[str, object] | None:
        value = cell.strip()
        for fmt in self.formats:
            m = _compile(column, fmt).fullmatch(value)
            if m is None:
                continue
            month = m["month"]
            month_number = int(month) if month.isdigit() else MONTH_NUMBERS[month.lower()]
            try:
                day = date(int(m["year"]), month_number, int(m["day"]))
            except ValueError:
                continue
            return {column: day.isoformat()}
        return None


@dataclass(frozen=True)
class Quantity:
    """Split a number and a unit, such as ``90 min``, into the props ``number`` and ``unit``."""

    number: str
    unit: str
    units: Mapping[str, str]

    def check(self, column: str) -> None:
        for name in (self.number, self.unit):
            if name == "" or name != name.strip():
                raise ValueError(
                    f"settings: column {column!r}: quantity prop name {name!r} is empty "
                    f"or has white space around it"
                )
        if self.number == self.unit:
            raise ValueError(
                f"settings: column {column!r}: a quantity writes the prop {self.number!r} twice"
            )
        if not self.units:
            raise ValueError(f"settings: column {column!r}: a quantity needs a unit map")
        for spelling, unit in self.units.items():
            if unit == "":
                raise ValueError(
                    f"settings: column {column!r}: unit spelling {spelling!r} maps to an empty unit"
                )

    def as_json(self) -> dict[str, object]:
        return {
            "kind": "quantity",
            "number": self.number,
            "unit": self.unit,
            "units": dict(self.units),
        }

    def kinds(self, column: str) -> dict[str, str]:
        return {self.number: "number", self.unit: "text"}

    def fallback(self, column: str) -> str:
        return self.number

    def read(self, column: str, cell: str) -> dict[str, object] | None:
        m = QUANTITY.fullmatch(cell.strip())
        if m is None:
            return None
        x = _number(m[1])
        unit = self.units.get(m[2])
        if x is None or unit is None:
            return None
        return {self.number: x, self.unit: unit}


@dataclass(frozen=True)
class Integer:
    """Read an integer within +/-(2**53 - 1)."""

    def check(self, column: str) -> None:
        pass

    def as_json(self) -> dict[str, object]:
        return {"kind": "integer"}

    def kinds(self, column: str) -> dict[str, str]:
        return {column: "integer"}

    def fallback(self, column: str) -> str:
        return column

    def read(self, column: str, cell: str) -> dict[str, object] | None:
        value = cell.strip()
        if INTEGER.fullmatch(value) is None:
            return None
        n = int(value)
        return {column: n} if abs(n) <= MAX_SAFE_INTEGER else None


@dataclass(frozen=True)
class Number:
    """Read a decimal number that is a finite double."""

    def check(self, column: str) -> None:
        pass

    def as_json(self) -> dict[str, object]:
        return {"kind": "number"}

    def kinds(self, column: str) -> dict[str, str]:
        return {column: "number"}

    def fallback(self, column: str) -> str:
        return column

    def read(self, column: str, cell: str) -> dict[str, object] | None:
        x = _number(cell.strip())
        return None if x is None else {column: x}


@dataclass(frozen=True)
class Boolean:
    """Read ``true`` or ``false`` from the spellings given, compared exactly."""

    true: tuple[str, ...]
    false: tuple[str, ...]

    def check(self, column: str) -> None:
        for name, spellings in (("true", self.true), ("false", self.false)):
            if not spellings:
                raise ValueError(f"settings: column {column!r}: a boolean needs a {name} spelling")
            for s in spellings:
                if s == "":
                    raise ValueError(f"settings: column {column!r}: a {name} spelling is empty")
                if s != s.strip():
                    raise ValueError(
                        f"settings: column {column!r}: {name} spelling {s!r} has white space "
                        f"around it, which a value never has once read"
                    )
        both = sorted(set(self.true) & set(self.false), key=lambda s: s.encode("utf-8"))
        if both:
            raise ValueError(
                f"settings: column {column!r}: spelling {both[0]!r} is both true and false"
            )

    def as_json(self) -> dict[str, object]:
        return {"kind": "boolean", "true": list(self.true), "false": list(self.false)}

    def kinds(self, column: str) -> dict[str, str]:
        return {column: "boolean"}

    def fallback(self, column: str) -> str:
        return column

    def read(self, column: str, cell: str) -> dict[str, object] | None:
        value = cell.strip()
        if value in self.true:
            return {column: True}
        if value in self.false:
            return {column: False}
        return None


type Conversion = Date | Quantity | Integer | Number | Boolean


def prop_kinds(props: Sequence[str], convert: Mapping[str, Conversion]) -> dict[str, str]:
    """The declared kinds of the props written for the prop columns ``props`` (section 3.4)."""
    kinds: dict[str, str] = {}
    for p in props:
        conversion = convert.get(p)
        kinds.update({p: "text"} if conversion is None else conversion.kinds(p))
    return kinds


def check_conversions(props: Sequence[str], convert: Mapping[str, Conversion]) -> None:
    """Refuse conversions of columns that are not props, bad conversions and clashing props."""
    for column in sorted(convert, key=lambda c: c.encode("utf-8")):
        if column not in props:
            raise ValueError(f"settings: convert names column {column!r}, which is not in props")
        convert[column].check(column)
    written: dict[str, str] = {}
    for p in props:
        conversion = convert.get(p)
        for name in [p] if conversion is None else conversion.kinds(p):
            if name in written:
                raise ValueError(
                    f"settings: the prop {name!r} would be written twice, "
                    f"for columns {written[name]!r} and {p!r}"
                )
            written[name] = p
