"""A CSV tessera's settings, read from a settings file (issue #18).

The file has the shape of the tessera's ``header.settings`` (:meth:`Settings.as_json`): a
mapping with ``type``, ``key``, ``label``, ``summary``, ``props``, ``encoding``, ``delimiter``
and ``convert``, each optional with :class:`Settings`'s default. ``convert`` maps a prop column
to a conversion written as its ``as_json`` form, such as ``{kind: date, formats: [...]}``. So
the ``header.settings`` of a tessera, as a file, rebuilds that tessera from the same source.
In YAML a boolean conversion's keys are quoted, ``"true"`` and ``"false"``: bare, they are
booleans, and a key must be text.

The file is read as YAML 1.2 core schema, which holds JSON, with duplicate keys refused. A key
the settings do not have, a value of the wrong kind and settings the builder refuses are errors
naming the file, the line and the setting. Nothing is guessed.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mosaic_format.yaml_core import load

from mosaic_build.tessera.convert import Boolean, Conversion, Date, Integer, Number, Quantity
from mosaic_build.tessera.csv import Settings, check_settings

__all__ = ["SettingsError", "conversion", "from_json", "read"]

type _Where = tuple[str, ...]

_FIELDS: Mapping[str, tuple[str, ...]] = {
    "date": ("formats",),
    "quantity": ("number", "unit", "units"),
    "integer": (),
    "number": (),
    "boolean": ("true", "false"),
}
"""Each conversion kind and the fields it needs, besides ``kind``."""


class SettingsError(ValueError):
    """A setting that cannot be read; ``where`` is its place in the settings, key by key."""

    def __init__(self, where: _Where, message: str) -> None:
        super().__init__(message)
        self.where = where
        self.message = message


def _name(where: _Where) -> str:
    return ".".join(where)


def _text(value: object, where: _Where, *, null: bool = False) -> str | None:
    if isinstance(value, str) or (null and value is None):
        return value
    kind = "text or null" if null else "text"
    raise SettingsError(where, f"{_name(where)} must be {kind}, not {value!r}")


def _texts(value: object, where: _Where) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SettingsError(where, f"{_name(where)} must be a list of text, not {value!r}")
    return tuple(value)


def _mapping(value: object, where: _Where, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SettingsError(where, f"{_name(where) or 'the settings'} must be a mapping of {what}")
    return value


def conversion(value: object, where: _Where) -> Conversion:
    """The conversion that ``value``, its ``as_json`` form, declares."""
    fields = _mapping(value, where, "a conversion's fields")
    kind = fields.get("kind")
    if not isinstance(kind, str) or kind not in _FIELDS:
        kinds = ", ".join(_FIELDS)
        raise SettingsError(
            (*where, "kind"), f"{_name(where)}: kind {kind!r} is no conversion; one of {kinds}"
        )
    wanted = _FIELDS[kind]
    for key in fields:
        if key != "kind" and key not in wanted:
            raise SettingsError(
                (*where, key), f"{_name(where)}: a {kind} conversion has no field {key!r}"
            )
    for key in wanted:
        if key not in fields:
            raise SettingsError(where, f"{_name(where)}: a {kind} conversion needs {key!r}")
    match kind:
        case "date":
            return Date(_texts(fields["formats"], (*where, "formats")))
        case "quantity":
            units = _mapping(fields["units"], (*where, "units"), "spellings to units")
            return Quantity(
                number=str(_text(fields["number"], (*where, "number"))),
                unit=str(_text(fields["unit"], (*where, "unit"))),
                units={k: str(_text(v, (*where, "units", k))) for k, v in units.items()},
            )
        case "integer":
            return Integer()
        case "number":
            return Number()
        case _:
            return Boolean(
                true=_texts(fields["true"], (*where, "true")),
                false=_texts(fields["false"], (*where, "false")),
            )


def from_json(value: object) -> Settings:
    """The settings that ``value``, a mapping in the shape of ``header.settings``, gives."""
    given = _mapping(value, (), "settings")
    defaults = Settings()
    known = ("type", "key", "label", "summary", "props", "encoding", "delimiter", "convert")
    for key in given:
        if key not in known:
            raise SettingsError((key,), f"{key!r} is no setting; the settings are {known}")
    convert = _mapping(given.get("convert", {}), ("convert",), "prop columns to conversions")
    return Settings(
        type=str(_text(given.get("type", defaults.type), ("type",))),
        key=_text(given.get("key"), ("key",), null=True),
        label=_text(given.get("label"), ("label",), null=True),
        summary=_text(given.get("summary"), ("summary",), null=True),
        props=_texts(given.get("props", []), ("props",)),
        encoding=str(_text(given.get("encoding", defaults.encoding), ("encoding",))),
        delimiter=str(_text(given.get("delimiter", defaults.delimiter), ("delimiter",))),
        convert={c: conversion(v, ("convert", c)) for c, v in convert.items()},
    )


def read(path: str | os.PathLike[str]) -> Settings:
    """Read and check the settings file ``path``.

    Raises :class:`ValueError` naming the file, and the line when known, for a file that is
    not UTF-8 YAML or holds settings the builder refuses; :class:`OSError` when it cannot be
    read.
    """
    file = Path(path)
    try:
        text = file.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{file}: settings: not UTF-8 text (byte {e.start})") from None
    doc = load(text, str(file))  # YamlError names the file and line
    try:
        settings = from_json(doc.data)
        check_settings(settings)
    except SettingsError as e:
        line = doc.line(e.where)
        at = str(file) if line is None else f"{file}:{line}"
        raise ValueError(f"{at}: settings: {e.message}") from None
    except ValueError as e:
        raise ValueError(f"{file}: {e}") from None
    return settings
