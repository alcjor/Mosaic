from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src" / "mosaic_mock"
OTHERS = ("mosaic_core", "mosaic_extractors", "mosaic_server", "mosaic_cli")
REAL_MISSIONS = (
    "Sentinel",
    "Galileo",
    "Rosetta",
    "MetOp",
    "Copernicus",
    "Hubble",
    "Juice",
    "Envisat",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.req("MOCK-01")
def test_mocker_imports_no_mosaic_package() -> None:
    for f in SRC.rglob("*.py"):
        assert not (_imports(f) & set(OTHERS)), f


@pytest.mark.req("MOCK-03")
def test_engine_knows_no_profile() -> None:
    for f in (SRC / "engine").rglob("*.py"):
        mods = {
            n.module
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
            if isinstance(n, ast.ImportFrom) and n.module
        }
        assert not any(m.startswith("mosaic_mock.profiles") for m in mods), f


@pytest.mark.req("MOCK-05")
def test_two_profiles_ship() -> None:
    from mosaic_mock import profiles

    assert set(profiles.NAMES) == {"spacecraft", "toy"}
    for name in profiles.NAMES:
        assert profiles.get(name).sizes["small"]


@pytest.mark.req("MOCK-04")
def test_everything_is_invented(small) -> None:
    _, gen = small
    blob = b"\n".join(gen.files.values()).decode("utf-8", errors="ignore")
    for name in REAL_MISSIONS:
        assert name not in blob
