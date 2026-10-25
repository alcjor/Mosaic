"""Named, independent random streams (MOCK-31: no global `random`, no clock)."""

from __future__ import annotations

import hashlib
import random


class Rng:
    """Derives one `random.Random` per stream name from ``(seed, name)``.

    Adding a stream never reshuffles another, so snapshots stay stable.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def stream(self, name: str) -> random.Random:
        r = self._streams.get(name)
        if r is None:
            digest = hashlib.sha256(f"{self.seed}:{name}".encode()).digest()
            r = random.Random(int.from_bytes(digest[:8], "big"))
            self._streams[name] = r
        return r
