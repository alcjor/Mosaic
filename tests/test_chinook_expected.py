"""The Chinook fixture's expected hashes (Specification 0.1, section 11; plan M3.3).

``conformance/fixtures/chinook/expected-hashes.json`` names the knowledge hash, vector hash and
model of a clean build of the fixture's one target. The slow test builds and compares; these fast
tests check that the file names every target of the pattern, that the pattern pins its piece by a
full hash (section 5.1), and that a build whose knowledge or vector hash differs from the file
fails the slow test.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from mosaic_format.yaml_core import load

from tests.conftest import REPO
from tests.fixtures import test_chinook
from tests.fixtures.expected import FILE, load_expected, pattern_targets
from tests.fixtures.test_netflix import Run

CHINOOK = REPO / "conformance" / "fixtures" / "chinook"
OTHER = "f" * 64


def test_the_chinook_fixture_has_expected_hashes_for_every_target() -> None:
    expected = load_expected(CHINOOK)
    assert sorted(expected) == pattern_targets(CHINOOK / "pattern.yaml") == ["default"]
    # The pattern's target builds vectors (the default), with the model of section 6.
    assert expected["default"].vector_hash is not None
    assert expected["default"].embed_model == (
        "snowflake-arctic-embed-xs@e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
    )


def test_the_pattern_pins_its_one_piece_by_a_full_hash() -> None:
    data = load((CHINOOK / "pattern.yaml").read_text(encoding="utf-8"), "pattern.yaml").data
    [piece] = data["pieces"]
    name, _, pinned = piece.partition("@")
    assert name == "chinook"
    assert len(pinned) == 64 and set(pinned) <= set("0123456789abcdef")


def _run() -> Run:
    """A run of the Chinook flow that gives exactly the expected hashes."""
    entry = load_expected(CHINOOK)[test_chinook.TARGET]
    return Run(
        tessera_hash="0" * 64,
        tessera_size=0,
        mosaic_hash=entry.knowledge_hash,
        vector_hash=entry.vector_hash,
        embed_model=entry.embed_model,
        vectors=1,
        nodes=1,
        mosaic_size=0,
        mosaic_bytes=b"",
        report={},
        seconds={},
    )


def test_the_chinook_slow_test_passes_on_the_expected_hashes() -> None:
    run = _run()
    test_chinook.test_each_build_has_the_expected_hashes((run, run))


@pytest.mark.parametrize("field", ["mosaic_hash", "vector_hash"])
def test_the_chinook_slow_test_fails_when_a_build_hash_differs(field: str) -> None:
    good = _run()
    bad = replace(good, **{field: OTHER})
    with pytest.raises(AssertionError):
        test_chinook.test_each_build_has_the_expected_hashes((good, bad))
    with pytest.raises(AssertionError):
        test_chinook.test_each_build_has_the_expected_hashes((bad, good))


@pytest.mark.parametrize("field", ["knowledge_hash", "vector_hash"])
def test_the_chinook_slow_test_fails_when_the_expected_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    run = _run()  # read before the change: the hashes a build gives
    data = json.loads((CHINOOK / FILE).read_text(encoding="utf-8"))
    data["mosaics"][test_chinook.TARGET][field] = OTHER
    changed = tmp_path / "chinook"
    changed.mkdir()
    (changed / FILE).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(test_chinook, "FIXTURE", changed)
    with pytest.raises(AssertionError, match=field):
        test_chinook.test_each_build_has_the_expected_hashes((run, run))
