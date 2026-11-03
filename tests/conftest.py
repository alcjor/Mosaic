from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "spec"


@pytest.fixture
def spec_dir() -> Path:
    return SPEC
