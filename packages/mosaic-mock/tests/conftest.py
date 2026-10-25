from __future__ import annotations

import json
from pathlib import Path

import pytest
from mosaic_mock import profiles
from mosaic_mock.engine.generate import Generated, generate, write


@pytest.fixture(scope="session")
def small(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Generated]:
    """The small clean spacecraft mission, generated once and written to disk."""
    gen = generate(profiles.get("spacecraft"))
    out = tmp_path_factory.mktemp("demosat")
    write(out, gen)
    return out, gen


@pytest.fixture(scope="session")
def toy(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Generated]:
    gen = generate(profiles.get("toy"))
    out = tmp_path_factory.mktemp("toy")
    write(out, gen)
    return out, gen


def load_truth(root: Path) -> dict:
    return json.loads((root / "ground_truth.json").read_text(encoding="utf-8"))
