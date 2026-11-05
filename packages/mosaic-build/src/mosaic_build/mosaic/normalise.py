"""Normalisation steps for canonical keys (Specification 0.1, section 5.2).

Each step is a function from text to text; a type's ``normalise`` list applies them in order,
``[trim]`` by default. White space is the Unicode ``White_Space`` property, the 25 code points
section 5.2 lists: neither ``str.isspace`` (which adds U+001C-U+001F) nor ``str.strip()``
without arguments is exactly that set (decision 8 on #14).

``upper`` and ``lower`` use Unicode *simple* case mapping, one code point to one code point,
so a key never grows: ``ß`` stays ``ß`` under ``upper`` and ``\u0130`` (U+0130) becomes ``i``
under ``lower``. Python offers only the full mappings (``str.upper``, ``str.lower``); the
simple mapping of a code point is its full mapping when that is one code point, and otherwise
the single titlecase code point where one exists (the Greek letters with ypogegrammeni, such
as U+1F80 → U+1F88) or the code point itself. Lower case has one exception, U+0130. Mapping
code point by code point also keeps ``lower`` free of the context rule for final sigma. The
mapping follows the Unicode version of Python's ``unicodedata``.
"""

from collections.abc import Callable, Mapping, Sequence

WHITE_SPACE = frozenset(
    "\t\n\x0b\x0c\r \x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)
"""The characters with the Unicode ``White_Space`` property (section 5.2)."""

_WHITE_SPACE_TEXT = "".join(sorted(WHITE_SPACE))

DEFAULT_STEPS = ("trim",)
"""The steps of a type that names none (section 5.2)."""


def _simple_upper(c: str) -> str:
    full = c.upper()
    if len(full) == 1:
        return full
    title = c.title()
    return title if len(title) == 1 else c


def _simple_lower(c: str) -> str:
    if c == "\u0130":
        return "i"
    full = c.lower()
    return full if len(full) == 1 else c


def trim(text: str) -> str:
    """Remove leading and trailing white space."""
    return text.strip(_WHITE_SPACE_TEXT)


def upper(text: str) -> str:
    """Upper case by Unicode simple case mapping."""
    return "".join(_simple_upper(c) for c in text)


def lower(text: str) -> str:
    """Lower case by Unicode simple case mapping."""
    return "".join(_simple_lower(c) for c in text)


def collapse_spaces(text: str) -> str:
    """Turn every run of white space into one space (U+0020)."""
    out: list[str] = []
    in_run = False
    for c in text:
        if c in WHITE_SPACE:
            if not in_run:
                out.append(" ")
            in_run = True
        else:
            out.append(c)
            in_run = False
    return "".join(out)


def dash_to_underscore(text: str) -> str:
    """Turn every ``-`` (U+002D) into ``_``."""
    return text.replace("-", "_")


def underscore_to_dash(text: str) -> str:
    """Turn every ``_`` into ``-`` (U+002D)."""
    return text.replace("_", "-")


STEPS: Mapping[str, Callable[[str], str]] = {
    "trim": trim,
    "upper": upper,
    "lower": lower,
    "collapse-spaces": collapse_spaces,
    "dash-to-underscore": dash_to_underscore,
    "underscore-to-dash": underscore_to_dash,
}
"""Every normalisation step of section 5.2, by its name in the pattern."""


def normalise(text: str, steps: Sequence[str] = DEFAULT_STEPS) -> str:
    """Apply ``steps`` to ``text`` in order. Raises :class:`KeyError` for an unknown step."""
    for step in steps:
        text = STEPS[step](text)
    return text
