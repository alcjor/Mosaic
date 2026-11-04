"""The normative files of Specification 0.1, loaded at runtime.

An installed wheel carries them as package data in ``mosaic_format/spec/``; an editable
install (the repository checkout) reads ``<repo>/spec`` directly, so they are never copied
by hand.
"""

import json
from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from mosaic_format import NORMATIVE_FILES

JSON_SCHEMAS = ("pattern", "proposals", "build-report", "answers")
"""The four JSON Schemas (draft 2020-12), by name; the file is ``<name>.schema.json``."""

_REPO_SPEC = Path(__file__).resolve().parents[4] / "spec"


@cache
def spec_dir() -> Traversable:
    """The directory holding the five normative files: packaged, else the repository's."""
    packaged = files("mosaic_format") / "spec"
    if all((packaged / name).is_file() for name in NORMATIVE_FILES):
        return packaged
    if all((_REPO_SPEC / name).is_file() for name in NORMATIVE_FILES):
        return _REPO_SPEC
    raise FileNotFoundError(
        f"normative files not found in the package ({packaged}) or the repository ({_REPO_SPEC})"
    )


def read_text(name: str) -> str:
    """The text of one normative file, such as ``format.sql``."""
    if name not in NORMATIVE_FILES:
        raise ValueError(f"{name!r} is not a normative file; expected one of {NORMATIVE_FILES}")
    return (spec_dir() / name).read_text(encoding="utf-8")


def format_sql() -> str:
    """``format.sql``: the SQLite schema of tesserae and mosaics."""
    return read_text("format.sql")


def json_schema(name: str) -> dict[str, Any]:
    """One of the four JSON Schemas, parsed; ``name`` is one of :data:`JSON_SCHEMAS`."""
    if name not in JSON_SCHEMAS:
        raise ValueError(f"{name!r} is not a JSON Schema; expected one of {JSON_SCHEMAS}")
    return json.loads(read_text(f"{name}.schema.json"))
