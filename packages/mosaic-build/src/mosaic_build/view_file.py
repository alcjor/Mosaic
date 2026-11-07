"""Read a view file: what ``mosaic view`` and ``mosaic export`` show (plan M3.5).

docs/design.md, Implementation plan, "View file": YAML, used by both view and export; it sets
which types appear, columns, what a node page shows, labels, theme, which types an export
carries, and ``search: semantic`` or ``search: text``. The keys, values and defaults are those
of ``views/example.yaml`` (answer on #120); ``views/view.schema.json`` is their JSON Schema.

- ``search``: ``semantic`` (the default) or ``text``.
- ``theme``: ``auto`` (the default, following the system), ``light`` or ``dark``.
- ``types``: the node types that appear, in the order written; by default every node type, by
  name. Each maps to ``label`` (shown instead of the type name), ``columns`` (its table: the
  node's name, then these properties; by default every declared property), ``page`` (its node
  page: these properties and edge types, in this order; by default all of them) and ``names``
  (labels for its property and edge type names). A type left out is absent from the type list
  and tables only: search and links still reach its nodes, and the kit is not shaped by the
  view file (answer on #120, Reading A).
- ``export.types``: which node types an export carries (answer on #140). The export carries a
  mosaic built from the source as its one piece with those types as its target's ``types``
  (:mod:`mosaic_build.cut`); a type the mosaic lacks, or an empty list, is an error. By
  default, the mosaic as it is.

Every key is optional, so an empty view file, or none (``read(None)``), gives M2's viewer. The
file is read as YAML 1.2 core schema with duplicate keys refused. An unknown key and a value of
the wrong kind are errors naming the file, the line and the setting. Whether the named types and
properties are in the mosaic is not checked here: the page does that, against the mosaic it
opens (M3.6).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mosaic_format.yaml_core import load

__all__ = ["SEARCH", "THEMES", "TypeView", "ViewFileError", "ViewSettings", "from_json", "read"]

SEARCH = ("semantic", "text")
"""The values of ``search``; the first is the default."""
THEMES = ("auto", "light", "dark")
"""The values of ``theme``; the first is the default."""

_KEYS = ("search", "theme", "types", "export")
_TYPE_KEYS = ("label", "columns", "page", "names")
_EXPORT_KEYS = ("types",)

type _Where = tuple[str | int, ...]
"""Where a value lies in the file: mapping keys and list indexes from the root."""


@dataclass(frozen=True)
class TypeView:
    """How one node type appears; ``None`` is the default (see the module)."""

    name: str
    label: str | None = None
    columns: tuple[str, ...] | None = None
    page: tuple[str, ...] | None = None
    names: Mapping[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "columns": None if self.columns is None else list(self.columns),
            "page": None if self.page is None else list(self.page),
            "names": dict(self.names),
        }


@dataclass(frozen=True)
class ViewSettings:
    """A view file's settings; the defaults are M2's viewer."""

    search: str = SEARCH[0]
    theme: str = THEMES[0]
    types: tuple[TypeView, ...] | None = None
    export_types: tuple[str, ...] | None = None

    def as_json(self) -> dict[str, Any]:
        """The settings as JSON data, for the page; ``null`` is a default the page applies."""
        return {
            "search": self.search,
            "theme": self.theme,
            "types": None if self.types is None else [t.as_json() for t in self.types],
            "export": {"types": None if self.export_types is None else list(self.export_types)},
        }


class ViewFileError(ValueError):
    """A setting that cannot be read; ``where`` is its place in the file."""

    def __init__(self, where: _Where, message: str) -> None:
        super().__init__(message)
        self.where = where
        self.message = message


def _name(where: _Where) -> str:
    """The setting's name, such as ``types.A.columns``; list indexes name their list."""
    return ".".join(str(w) for w in where if isinstance(w, str)) or "view file"


def _mapping(value: object, where: _Where, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ViewFileError(where, f"{_name(where)} must be a mapping of {what}")
    return value


def _unknown(where: _Where, known: tuple[str, ...]) -> ViewFileError:
    return ViewFileError(where, f"{_name(where)}: no such setting; one of {', '.join(known)}")


def _one_of(value: object, where: _Where, values: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in values:
        raise ViewFileError(
            where, f"{_name(where)} must be one of {', '.join(values)}, not {value!r}"
        )
    return value


def _text(value: object, where: _Where) -> str:
    if not isinstance(value, str) or not value:
        raise ViewFileError(where, f"{_name(where)} must be non-empty text, not {value!r}")
    return value


def _texts(value: object, where: _Where) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ViewFileError(where, f"{_name(where)} must be a list of names, not {value!r}")
    seen: set[str] = set()
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ViewFileError(
                (*where, i), f"{_name(where)}: item {i + 1} must be a non-empty name, not {item!r}"
            )
        if item in seen:
            raise ViewFileError((*where, i), f"{_name(where)} names {item!r} twice")
        seen.add(item)
    return tuple(value)


def _names(value: object, where: _Where) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ViewFileError(
            where, f"{_name(where)} must be a mapping of property and edge names to labels"
        )
    for key in value:
        if not key:
            raise ViewFileError((*where, key), f"{_name(where)}: a name must be non-empty text")
    return {k: _text(v, (*where, k)) for k, v in value.items()}


def _type_view(name: str, value: object, where: _Where) -> TypeView:
    got: dict[str, Any] = {}
    for key, item in _mapping(value, where, "a type's settings").items():  # in the order written
        at = (*where, key)
        match key:
            case "label":
                got[key] = _text(item, at)
            case "columns" | "page":
                got[key] = _texts(item, at)
            case "names":
                got[key] = _names(item, at)
            case _:
                raise _unknown(at, _TYPE_KEYS)
    return TypeView(
        name=name,
        label=got.get("label"),
        columns=got.get("columns"),
        page=got.get("page"),
        names=got.get("names", {}),
    )


def _types(value: object) -> tuple[TypeView, ...]:
    if not isinstance(value, dict):
        raise ViewFileError(("types",), "types must be a mapping of type names to settings")
    views = []
    for name, entry in value.items():
        if not name:
            raise ViewFileError(("types", name), "types: a type name must be non-empty text")
        views.append(_type_view(name, entry, ("types", name)))
    return tuple(views)


def _export_types(value: object) -> tuple[str, ...] | None:
    got = None
    for key, item in _mapping(value, ("export",), "export settings").items():
        if key != "types":
            raise _unknown(("export", key), _EXPORT_KEYS)
        got = _texts(item, ("export", "types"))
    return got


def from_json(value: object) -> ViewSettings:
    """The settings that ``value``, a view file's data, gives; ``None`` is an empty file.

    The settings are read in the order written, so of several wrong ones the first is named.
    """
    if value is None:
        return ViewSettings()
    got: dict[str, Any] = {}
    for key, item in _mapping(value, (), "settings").items():
        match key:
            case "search":
                got[key] = _one_of(item, (key,), SEARCH)
            case "theme":
                got[key] = _one_of(item, (key,), THEMES)
            case "types":
                got[key] = _types(item)
            case "export":
                got[key] = _export_types(item)
            case _:
                raise _unknown((key,), _KEYS)
    return ViewSettings(
        search=got.get("search", SEARCH[0]),
        theme=got.get("theme", THEMES[0]),
        types=got.get("types"),
        export_types=got.get("export"),
    )


def read(path: str | os.PathLike[str] | None) -> ViewSettings:
    """Read and check the view file ``path``; with none, the defaults (M2's viewer).

    Raises :class:`ValueError` naming the file, and the line when known, for a file that is
    not UTF-8 YAML or holds a setting that cannot be read; :class:`OSError` when it cannot be
    read.
    """
    if path is None:
        return ViewSettings()
    file = Path(path)
    try:
        text = file.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{file}: view file: not UTF-8 text (byte {e.start})") from None
    doc = load(text, str(file))  # YamlError names the file and line
    try:
        return from_json(doc.data)
    except ViewFileError as e:
        line = doc.line(e.where)
        at = str(file) if line is None else f"{file}:{line}"
        raise ValueError(f"{at}: view file: {e.message}") from None
