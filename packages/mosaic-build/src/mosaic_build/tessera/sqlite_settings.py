"""A SQLite tessera's settings, read from a settings file (plan M3.2).

The file has the shape of the tessera's ``header.settings`` (:meth:`Settings.as_json`): a
mapping with one key, ``tables``, which maps each table to read, by its name in the database, to
its settings: ``type``, ``label``, ``summary``, ``props``, ``convert`` and ``foreign_keys``, each
optional with :class:`Table`'s default (``type`` is the table's name; no label, summary, props,
conversions or foreign keys). ``convert`` maps a prop column to a conversion written as its
``as_json`` form, as in a CSV tessera's settings file (``mosaic_build.tessera.settings``);
``foreign_keys`` maps a foreign key's column to the name of its edge type. A table whose primary
key is two foreign keys takes ``edge`` alone, the name of the edge type each of its rows gives
(plan M3.13). The tables keep the file's order. So the ``header.settings`` of a tessera, as a
file, rebuilds that tessera from the same database.

The file is read as YAML 1.2 core schema, which holds JSON, with duplicate keys refused. A key
the settings do not have, a value of the wrong kind and settings the builder refuses, alone or
for the database (:func:`read_database`: a table or column it does not have, a foreign key it
does not declare), are errors naming the file, the line and the setting. Nothing is guessed.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mosaic_format.writer import Content
from mosaic_format.yaml_core import Document, load

from mosaic_build.tessera import sqlite
from mosaic_build.tessera.settings import SettingsError, conversion
from mosaic_build.tessera.sqlite import SettingError, Settings, Table, Where, check_settings

__all__ = ["SettingsFile", "from_json", "load_file", "read", "read_database"]

_SETTINGS = ("tables",)
"""The settings' keys."""
_TABLE = ("type", "label", "summary", "props", "convert", "foreign_keys", "edge")
"""A table's settings."""


type _Where = tuple[str, ...]
"""A setting's place in the file, key by key."""


def _name(where: _Where) -> str:
    return ".".join(str(w) for w in where)


def _mapping(value: object, where: _Where, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        name = _name(where) or "the settings"
        raise SettingsError(where, f"{name} must be a mapping of {what}")
    return value


def _text(value: object, where: _Where, *, null: bool = False) -> str | None:
    if isinstance(value, str) or (null and value is None):
        return value
    kind = "text or null" if null else "text"
    raise SettingsError(where, f"{_name(where)} must be {kind}, not {value!r}")


def _texts(value: object, where: _Where) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SettingsError(where, f"{_name(where)} must be a list of text, not {value!r}")
    return tuple(value)


def _table(value: object, where: _Where) -> Table:
    given = _mapping(value, where, "its settings")
    for key in given:
        if key not in _TABLE:
            raise SettingsError(
                (*where, key), f"{_name((*where, key))} is no setting; one of {_TABLE}"
            )
    convert = _mapping(given.get("convert", {}), (*where, "convert"), "columns to conversions")
    fks = _mapping(given.get("foreign_keys", {}), (*where, "foreign_keys"), "columns to edges")
    return Table(
        type=None if "type" not in given else _text(given["type"], (*where, "type")),
        label=_text(given.get("label"), (*where, "label"), null=True),
        summary=_text(given.get("summary"), (*where, "summary"), null=True),
        props=_texts(given.get("props", []), (*where, "props")),
        convert={c: conversion(v, (*where, "convert", c)) for c, v in convert.items()},
        foreign_keys={c: str(_text(e, (*where, "foreign_keys", c))) for c, e in fks.items()},
        edge=None if "edge" not in given else _text(given["edge"], (*where, "edge")),
    )


def from_json(value: object) -> Settings:
    """The settings that ``value``, a mapping in the shape of ``header.settings``, gives."""
    given = _mapping(value, (), "settings")
    for key in given:
        if key not in _SETTINGS:
            raise SettingsError((key,), f"{key!r} is no setting; the settings are {_SETTINGS}")
    tables = _mapping(given.get("tables", {}), ("tables",), "table names to their settings")
    return Settings(tables={t: _table(v, ("tables", t)) for t, v in tables.items()})


@dataclass(frozen=True)
class SettingsFile:
    """The settings a file holds, and where each setting is in it."""

    path: Path
    settings: Settings
    document: Document

    def at(self, where: Where) -> str:
        """The file and the line of the setting at ``where`` (else of its nearest parent)."""
        line = self.document.line(where)
        return str(self.path) if line is None else f"{self.path}:{line}"


def load_file(path: str | os.PathLike[str]) -> SettingsFile:
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
    except SettingsError as e:
        found = SettingsFile(file, Settings(), doc)
        raise ValueError(f"{found.at(e.where)}: settings: {e.message}") from None
    found = SettingsFile(file, settings, doc)
    try:
        check_settings(settings)
    except SettingError as e:
        raise ValueError(f"{found.at(e.where)}: {e}") from None
    return found


def read(path: str | os.PathLike[str]) -> Settings:
    """The settings of the settings file ``path`` (see :func:`load_file`)."""
    return load_file(path).settings


def read_database(
    source: str | os.PathLike[str], settings: SettingsFile
) -> tuple[Content, sqlite.Report]:
    """The tessera's content for the SQLite database ``source``, shaped by ``settings``.

    As :func:`mosaic_build.tessera.sqlite.read`, but a setting the database does not match is a
    ``ValueError`` that also names the settings file and the setting's line.
    """
    try:
        return sqlite.read(source, settings.settings)
    except SettingError as e:
        raise ValueError(f"{settings.at(e.where)}: {e}") from None
