"""Profiles: what a domain looks like (MOCK-03, MOCK-05)."""

from __future__ import annotations

from mosaic_mock.engine.generate import Profile


def get(name: str) -> Profile:
    if name == "spacecraft":
        from mosaic_mock.profiles.spacecraft import SpacecraftProfile

        return SpacecraftProfile()
    if name == "toy":
        from mosaic_mock.profiles.toy import ToyProfile

        return ToyProfile()
    raise KeyError(f"unknown profile {name!r}; known: {', '.join(NAMES)}")


NAMES = ("spacecraft", "toy")
