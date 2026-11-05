"""The target a build makes (Specification 0.1, sections 3.3 and 5.4).

Each entry of the pattern's ``mosaics`` is one target, and defaults apply to omitted fields. A
pattern without ``mosaics`` has one target, named ``default``, with every default; building a
target the pattern does not define fails with ``invalid_input`` (decision Q7 on #16).

The header's ``settings`` are the target's entry with every default filled in, as canonical
JSON, with ``budget`` only when it is given (section 3.3, decision Q6 on #16).

A ``budget`` is in decimal units (1 KB = 1,000 bytes), rounded down to whole bytes, and is
compared with the size of the sealed file (decision Q4 on #16).
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mosaic_format.canonical_json import canonical_json

from mosaic_build.mosaic.errors import BuildError

DEFAULT_TARGET = "default"
"""The name of the one target of a pattern without ``mosaics`` (section 5.4)."""

DEFAULTS: Mapping[str, Any] = {
    "types": "all",
    "trust": "reviewed",
    "text": "snippets",
    "vectors": True,
    "evidence": "primary",
    "strict": False,
}
"""The default of each target field that has one (section 5.4); ``budget`` has none."""

_UNITS = {"B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000}
_BUDGET = re.compile(r"^([0-9]+(?:\.[0-9]+)?) ?(B|KB|MB|GB)$")


def budget_bytes(text: str) -> int:
    """A budget such as ``20 MB`` in bytes: decimal units, rounded down to whole bytes."""
    match = _BUDGET.match(text)
    if match is None:
        raise ValueError(f"budget {text!r} is not a size such as '20 MB'")
    number, unit = match.groups()
    return int(Decimal(number) * _UNITS[unit])  # int() of a positive Decimal rounds down


@dataclass(frozen=True)
class Target:
    """One target of the pattern, with every default filled in."""

    name: str
    fields: Mapping[str, Any]
    """The entry's fields, defaults filled in; ``budget`` only when given."""

    @property
    def types(self) -> str | list[str]:
        return self.fields["types"]

    @property
    def trust(self) -> str | int | float:
        return self.fields["trust"]

    @property
    def text(self) -> str:
        return self.fields["text"]

    @property
    def vectors(self) -> bool:
        return self.fields["vectors"]

    @property
    def evidence(self) -> str:
        return self.fields["evidence"]

    @property
    def strict(self) -> bool:
        return self.fields["strict"]

    @property
    def budget(self) -> int | None:
        """The budget in bytes, or None when the target gives none."""
        text = self.fields.get("budget")
        return None if text is None else budget_bytes(text)

    def settings(self) -> str:
        """The header's ``settings`` (section 3.3): the entry, defaults filled in, canonical."""
        return canonical_json(json.dumps(dict(self.fields), ensure_ascii=False))

    def node_types(self, pattern: Mapping[str, Any]) -> list[str]:
        """The node types in scope, in pattern order."""
        declared = list(pattern["types"])
        return declared if self.types == "all" else [t for t in declared if t in self.types]


def target(pattern: Mapping[str, Any], name: str) -> Target:
    """The target ``name`` of a checked pattern, or the build fails with ``invalid_input``."""
    mosaics: Mapping[str, Any] = pattern.get("mosaics", {DEFAULT_TARGET: {}})
    if name not in mosaics:
        defined = ", ".join(repr(n) for n in mosaics) or "none"
        raise BuildError(
            "invalid_input",
            f"target {name!r} is not defined by the pattern (5.4); its targets: {defined}",
        )
    return Target(name=name, fields={**DEFAULTS, **mosaics[name]})
