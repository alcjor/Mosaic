"""Domain-neutral world: items and edges."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from mosaic_mock.engine.naming import Naming


@dataclass
class Item:
    type: str
    key: str
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.type}/{self.key}"


@dataclass(frozen=True)
class Edge:
    type: str
    src: str  # item ref, "TYPE/KEY"
    dst: str


class World:
    """Items in insertion order (deterministic), plus typed edges."""

    def __init__(self) -> None:
        self._items: dict[str, Item] = {}
        self.edges: list[Edge] = []
        self.naming = Naming()  # every surface string written, for uniqueness
        self.meta: dict[str, Any] = {}  # profile-specific model for the renderers

    def add(self, item: Item) -> Item:
        if item.ref in self._items:
            raise ValueError(f"duplicate item {item.ref}")
        self._items[item.ref] = item
        return item

    def link(self, type_: str, src: Item, dst: Item) -> None:
        self.edges.append(Edge(type_, src.ref, dst.ref))

    def get(self, ref: str) -> Item:
        return self._items[ref]

    def has(self, ref: str) -> bool:
        return ref in self._items

    def remove(self, ref: str) -> None:
        del self._items[ref]
        self.edges = [e for e in self.edges if ref not in (e.src, e.dst)]

    def of_type(self, type_: str) -> list[Item]:
        return [i for i in self._items.values() if i.type == type_]

    def __iter__(self) -> Iterator[Item]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
