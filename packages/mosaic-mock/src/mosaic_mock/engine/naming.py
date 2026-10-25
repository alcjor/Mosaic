"""Naming toolkit: ID schemes and uniqueness with an edit-distance guard.

No two registered IDs of equal length are within Hamming distance 1, so a one-character
typo of a valid ID never produces another valid ID (MOCK-26).
"""

from __future__ import annotations

import random


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein distance, stopping early once it exceeds ``cap``."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


class Naming:
    """Registry of every surface string the mocker writes (IDs and mnemonics)."""

    def __init__(self) -> None:
        self.used: set[str] = set()
        self._near: set[str] = set()  # wildcard variants of distance-guarded IDs

    @staticmethod
    def _variants(s: str) -> list[str]:
        return [s[:i] + "\0" + s[i + 1 :] for i in range(len(s))]

    def is_free(self, s: str, *, guard: bool = True) -> bool:
        if s in self.used:
            return False
        return not guard or not any(v in self._near for v in self._variants(s))

    def register(self, s: str, *, guard: bool = True) -> str:
        if not self.is_free(s, guard=guard):
            raise ValueError(f"name {s!r} is taken or within distance 1 of another")
        self.used.add(s)
        if guard:
            self._near.update(self._variants(s))
        return s

    def numbered_id(self, prefix: str, rng: random.Random, digits: int = 4) -> str:
        """A fresh ``prefix`` + ``digits`` digits ID, at distance ≥ 2 from every other."""
        top = 10**digits
        for _ in range(10_000):
            cand = f"{prefix}{rng.randrange(1, top):0{digits}d}"
            if self.is_free(cand):
                return self.register(cand)
        raise RuntimeError(f"ID space for {prefix!r} exhausted")

    def mnemonic(self, base: str) -> str:
        """``base``, or ``base_2``, ``base_3``… if taken (mnemonics are not distance-guarded)."""
        cand, n = base, 1
        while not self.is_free(cand, guard=False):
            n += 1
            cand = f"{base}_{n}"
        return self.register(cand, guard=False)
