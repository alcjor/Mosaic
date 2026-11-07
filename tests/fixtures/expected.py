"""A fixture's expected hashes (Specification 0.1, section 11: "the expected mosaic").

``conformance/fixtures/<fixture>/expected-hashes.json`` records, for each target of the fixture's
pattern, the knowledge hash (section 3.6) and the vector hash (section 3.7) that a clean build
must give, and the ``embed_model`` the vector hash was made with (section 6). Its shape::

    {
      "comment": "...",
      "mosaics": {
        "<target>": {
          "knowledge_hash": "<64 lowercase hex>",
          "vector_hash": "<64 lowercase hex>" | null,
          "embed_model": "<name>@<64 lowercase hex>" | null
        }
      }
    }

The file is CODEOWNERS-protected: agents propose it, the maintainer merges it. A slow fixture
test compares each build with it through :func:`differences`.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mosaic_format.yaml_core import load

FILE = "expected-hashes.json"
FIELDS = ("knowledge_hash", "vector_hash", "embed_model")
_HASH = re.compile(r"[0-9a-f]{64}")
_MODEL = re.compile(r"[^@\s]+@[0-9a-f]{64}")


@dataclass(frozen=True)
class Expected:
    """What one target's clean build must give."""

    knowledge_hash: str
    vector_hash: str | None
    embed_model: str | None


class ExpectedError(ValueError):
    """An expected-hashes file that does not have the shape above."""


class _Twice(Exception):
    def __init__(self, key: str) -> None:
        self.key = key


def _once(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A JSON object whose keys are all distinct: a target named twice is an error, not a guess."""
    found: dict[str, object] = {}
    for key, value in pairs:
        if key in found:
            raise _Twice(key)
        found[key] = value
    return found


def load_expected(fixture: Path) -> dict[str, Expected]:
    """Read ``fixture/expected-hashes.json``; raise :class:`ExpectedError` naming what is wrong."""
    path = fixture / FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_once)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExpectedError(f"{path}: {error}") from error
    except _Twice as twice:
        raise ExpectedError(f"{path}: `{twice.key}` is named twice") from twice
    if not isinstance(data, dict) or set(data) - {"comment", "mosaics"}:
        raise ExpectedError(f"{path}: the top level holds only `comment` and `mosaics`")
    mosaics = data.get("mosaics")
    if not isinstance(mosaics, dict) or not mosaics:
        raise ExpectedError(f"{path}: `mosaics` names at least one target")
    expected: dict[str, Expected] = {}
    for target, entry in sorted(mosaics.items()):
        where = f"{path}: mosaics.{target}"
        if not isinstance(entry, dict) or set(entry) != set(FIELDS):
            raise ExpectedError(f"{where} holds exactly {', '.join(FIELDS)}")
        knowledge, vector, model = (entry[f] for f in FIELDS)
        if not isinstance(knowledge, str) or not _HASH.fullmatch(knowledge):
            raise ExpectedError(f"{where}.knowledge_hash is not 64 lowercase hex characters")
        if vector is not None and (not isinstance(vector, str) or not _HASH.fullmatch(vector)):
            raise ExpectedError(f"{where}.vector_hash is not 64 lowercase hex characters")
        if model is not None and (not isinstance(model, str) or not _MODEL.fullmatch(model)):
            raise ExpectedError(f"{where}.embed_model is not <name>@<64 lowercase hex>")
        if (vector is None) != (model is None):
            raise ExpectedError(f"{where}: vector_hash and embed_model are both set or both null")
        expected[target] = Expected(knowledge, vector, model)
    return expected


def pattern_targets(pattern: Path) -> list[str]:
    """The targets of a pattern: its `mosaics`, or `default` when it has none (section 5.4)."""
    data = load(pattern.read_text(encoding="utf-8"), pattern.name).data
    mosaics = data.get("mosaics") if isinstance(data, dict) else None
    return sorted(mosaics) if isinstance(mosaics, dict) and mosaics else ["default"]


def differences(
    expected: dict[str, Expected],
    target: str,
    *,
    knowledge_hash: str,
    vector_hash: str | None,
    embed_model: str | None,
) -> list[str]:
    """Each way the build of ``target`` differs from what is expected; empty when it matches."""
    want = expected.get(target)
    if want is None:
        return [f"{FILE} has no entry for target `{target}`"]
    got = Expected(knowledge_hash, vector_hash, embed_model)
    return [
        f"{target}.{field}: expected {getattr(want, field)}, built {getattr(got, field)}"
        for field in FIELDS
        if getattr(want, field) != getattr(got, field)
    ]
