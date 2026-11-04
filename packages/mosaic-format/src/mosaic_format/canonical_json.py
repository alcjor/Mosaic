"""Canonical JSON text (Specification 0.1, section 3.1; decision on issue #59).

Every JSON text in a file (``header.settings``, ``type.props``, ``node.props``, ``edge.props``,
``evidence.via``, ``external_ref.locator``) is in the canonical form of RFC 8785, the JSON
Canonicalization Scheme, and is I-JSON (RFC 7493):

- no whitespace outside strings;
- object keys sorted by their UTF-16 code units (RFC 8785 section 3.2.3), unlike other text in
  the specification, which is ordered by UTF-8 bytes;
- strings escape only ``"``, ``\\`` and characters below U+0020, using ``\\b \\t \\n \\f \\r``
  where they exist and ``\\u00xx`` (lower-case hex) otherwise;
- numbers are IEEE 754 doubles written as ECMAScript's ``Number::toString`` writes them;
- no duplicate object keys, no unpaired surrogates, no NaN or infinity, and no integer outside
  +/-(2**53 - 1): such integers would change value, so they are stored as strings.

``canonical_json`` takes any JSON text and returns its canonical form, or raises ``ValueError``
saying what is not allowed. Canonical text is a fixed point: canonicalizing it again returns it
unchanged.
"""

import json
import math
from decimal import Decimal

MAX_SAFE_INTEGER = 2**53 - 1
"""The largest integer every IEEE 754 double reader holds exactly (I-JSON)."""


def canonical_json(text: str) -> str:
    """The RFC 8785 canonical form of the JSON ``text``; ``ValueError`` if it is not I-JSON."""
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=_constant,
            parse_int=_integer,
            parse_float=_float,
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON ({e.msg} at character {e.pos})") from None
    out = _write(value)
    try:
        out.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("contains an unpaired surrogate") from None
    return out


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate object key {key!r}")
        obj[key] = value
    return obj


def _constant(name: str) -> object:
    raise ValueError(f"{name} is not a JSON number")


def _integer(text: str) -> float:
    n = int(text)
    if abs(n) > MAX_SAFE_INTEGER:
        raise ValueError(f"integer {text} is outside +/-(2**53 - 1); store it as a string")
    return float(n)


def _float(text: str) -> float:
    x = float(text)
    if not math.isfinite(x):
        raise ValueError(f"number {text} is outside the range of a double")
    return x


def _key_order(key: str) -> bytes:
    try:
        return key.encode("utf-16-be")
    except UnicodeEncodeError:
        raise ValueError("contains an unpaired surrogate") from None


def _write(value: object) -> str:
    match value:
        case None:
            return "null"
        case True:
            return "true"
        case False:
            return "false"
        case str():
            return json.dumps(value, ensure_ascii=False)
        case float():
            return _number(value)
        case list():
            return "[" + ",".join(_write(v) for v in value) + "]"
        case dict():
            keys = sorted(value, key=_key_order)
            return "{" + ",".join(_write(k) + ":" + _write(value[k]) for k in keys) + "}"
        case _:
            raise TypeError(f"not a JSON value: {value!r}")


def _number(x: float) -> str:
    """ECMAScript ``Number::toString`` for a finite double (RFC 8785 section 3.2.2.3)."""
    if x == 0:
        return "0"  # also -0
    sign = "-" if x < 0 else ""
    # repr gives the shortest digit string that round-trips, as ECMAScript requires.
    parts = Decimal(repr(abs(x))).as_tuple()
    all_digits = "".join(str(d) for d in parts.digits)
    exponent = parts.exponent
    assert isinstance(exponent, int)
    n = len(all_digits) + exponent  # value = 0.d1d2... * 10**n
    s = all_digits.rstrip("0")
    k = len(s)
    if k <= n <= 21:
        body = s + "0" * (n - k)
    elif 0 < n <= 21:
        body = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * -n + s
    else:
        e = n - 1
        mantissa = s if k == 1 else s[0] + "." + s[1:]
        body = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + body
