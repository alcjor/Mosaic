from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "spec"
MODEL = (
    REPO / ".cache" / "model" / "snowflake-arctic-embed-xs@d8c86521100d3556476a063fc2342036d45c106f"
)
"""Where ``scripts/fetch_model.py`` puts the model files of section 6 by default (slow tests)."""


@pytest.fixture
def spec_dir() -> Path:
    return SPEC
