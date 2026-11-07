"""Expected hashes of the conformance fixtures (Specification 0.1, section 11; plan M3.12).

Each fixture's ``expected-hashes.json`` names, for every target of its pattern, the knowledge
hash (section 3.6), vector hash and model (sections 3.7, 6) a clean build must give. The slow
fixture tests build and compare; these fast tests check the files' shape and that a build whose
hash differs from the file fails the slow test.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.conftest import REPO
from tests.fixtures import test_netflix
from tests.fixtures.expected import (
    FILE,
    Expected,
    ExpectedError,
    differences,
    load_expected,
    pattern_targets,
)

FIXTURES = REPO / "conformance" / "fixtures"
NETFLIX = FIXTURES / "netflix"
MODEL = "snowflake-arctic-embed-xs@" + "e" * 64
OTHER = "f" * 64


def _write(directory: Path, data: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / FILE).write_text(json.dumps(data), encoding="utf-8")
    return directory


def _entry(knowledge: str = "a" * 64, vector: str | None = "b" * 64, model: str | None = MODEL):
    return {"knowledge_hash": knowledge, "vector_hash": vector, "embed_model": model}


# --- the files in the repository --------------------------------------------------------------


def test_the_netflix_fixture_has_expected_hashes_for_every_target() -> None:
    expected = load_expected(NETFLIX)
    assert sorted(expected) == pattern_targets(NETFLIX / "pattern.yaml") == ["default"]
    # The pattern's target builds vectors (the default), so the vector hash and model are set.
    assert expected["default"].vector_hash is not None
    assert expected["default"].embed_model is not None


@pytest.mark.parametrize(
    "fixture", sorted(p.parent for p in FIXTURES.glob(f"*/{FILE}")), ids=lambda p: p.name
)
def test_every_expected_hashes_file_is_well_formed_and_names_the_pattern_targets(
    fixture: Path,
) -> None:
    assert sorted(load_expected(fixture)) == pattern_targets(fixture / "pattern.yaml")


def test_the_netflix_expected_model_is_the_pinned_model() -> None:
    """The vector hash is the one made with the model of section 6, named as the build names it."""
    [entry] = load_expected(NETFLIX).values()
    assert entry.embed_model == (
        "snowflake-arctic-embed-xs@e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
    )


# --- comparing a build with the file ----------------------------------------------------------


def test_a_build_with_the_expected_hashes_has_no_differences() -> None:
    expected = {"default": Expected("a" * 64, "b" * 64, MODEL)}
    assert (
        differences(
            expected, "default", knowledge_hash="a" * 64, vector_hash="b" * 64, embed_model=MODEL
        )
        == []
    )


@pytest.mark.parametrize(
    ("field", "built"),
    [
        ("knowledge_hash", {"knowledge_hash": OTHER}),
        ("vector_hash", {"vector_hash": OTHER}),
        ("vector_hash", {"vector_hash": None, "embed_model": None}),
        ("embed_model", {"embed_model": "snowflake-arctic-embed-xs@" + OTHER}),
    ],
)
def test_each_differing_value_is_a_difference_naming_the_field(
    field: str, built: dict[str, str | None]
) -> None:
    expected = {"default": Expected("a" * 64, "b" * 64, MODEL)}
    values: dict[str, str | None] = {
        "knowledge_hash": "a" * 64,
        "vector_hash": "b" * 64,
        "embed_model": MODEL,
    }
    values.update(built)
    found = differences(
        expected,
        "default",
        knowledge_hash=str(values["knowledge_hash"]),
        vector_hash=values["vector_hash"],
        embed_model=values["embed_model"],
    )
    assert found
    assert any(f"default.{field}: expected" in line for line in found)


def test_a_target_the_file_does_not_name_is_a_difference() -> None:
    found = differences(
        {"default": Expected("a" * 64, None, None)},
        "small",
        knowledge_hash="a" * 64,
        vector_hash=None,
        embed_model=None,
    )
    assert found == [f"{FILE} has no entry for target `small`"]


# --- the Netflix slow test fails on a hash that differs ---------------------------------------


def _netflix_run() -> test_netflix.Run:
    """A run of the Netflix flow that gives exactly the expected hashes."""
    entry = load_expected(NETFLIX)[test_netflix.TARGET]
    return test_netflix.Run(
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


def test_the_netflix_slow_test_passes_on_the_expected_hashes() -> None:
    run = _netflix_run()
    test_netflix.test_each_build_has_the_expected_hashes((run, run))


@pytest.mark.parametrize("field", ["mosaic_hash", "vector_hash"])
def test_the_netflix_slow_test_fails_when_a_build_hash_differs(field: str) -> None:
    good = _netflix_run()
    bad = replace(good, **{field: OTHER})
    with pytest.raises(AssertionError):
        test_netflix.test_each_build_has_the_expected_hashes((good, bad))


def test_the_netflix_slow_test_fails_when_the_expected_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = json.loads((NETFLIX / FILE).read_text(encoding="utf-8"))
    data["mosaics"][test_netflix.TARGET]["knowledge_hash"] = OTHER
    monkeypatch.setattr(test_netflix, "FIXTURE", _write(tmp_path / "netflix", data))
    run = _netflix_run()  # read before the change: the hashes a build gives
    with pytest.raises(AssertionError, match="knowledge_hash"):
        test_netflix.test_each_build_has_the_expected_hashes((run, run))


# --- the file's shape -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "only `comment` and `mosaics`"),
        ({"mosaics": {}, "extra": 1}, "only `comment` and `mosaics`"),
        ({"mosaics": {}}, "at least one target"),
        ({"mosaics": {"default": {"knowledge_hash": "a" * 64}}}, "holds exactly"),
        ({"mosaics": {"default": {**_entry(), "size": 1}}}, "holds exactly"),
        ({"mosaics": {"default": _entry(knowledge="A" * 64)}}, "knowledge_hash is not"),
        ({"mosaics": {"default": _entry(knowledge="a" * 63)}}, "knowledge_hash is not"),
        ({"mosaics": {"default": _entry(vector="xyz")}}, "vector_hash is not"),
        ({"mosaics": {"default": _entry(model="no-hash")}}, "embed_model is not"),
        ({"mosaics": {"default": _entry(model=None)}}, "both set or both null"),
        ({"mosaics": {"default": _entry(vector=None)}}, "both set or both null"),
    ],
)
def test_a_malformed_file_is_an_error_naming_the_file_and_the_setting(
    tmp_path: Path, data: object, message: str
) -> None:
    fixture = _write(tmp_path / "fixture", data)
    with pytest.raises(ExpectedError, match=message) as error:
        load_expected(fixture)
    assert str(fixture / FILE) in str(error.value)


def test_a_target_named_twice_is_an_error_naming_it(tmp_path: Path) -> None:
    entry = json.dumps(_entry())
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / FILE).write_text(
        f'{{"mosaics": {{"default": {entry}, "default": {entry}}}}}', encoding="utf-8"
    )
    with pytest.raises(ExpectedError, match="`default` is named twice"):
        load_expected(fixture)


def test_a_target_without_vectors_has_no_vector_hash_and_no_model(tmp_path: Path) -> None:
    fixture = _write(tmp_path / "fixture", {"mosaics": {"small": _entry(vector=None, model=None)}})
    assert load_expected(fixture) == {"small": Expected("a" * 64, None, None)}


def test_a_missing_file_is_an_error_naming_it(tmp_path: Path) -> None:
    with pytest.raises(ExpectedError, match=FILE):
        load_expected(tmp_path)


def test_a_pattern_with_targets_names_each(tmp_path: Path) -> None:
    pattern = tmp_path / "pattern.yaml"
    pattern.write_text(
        (NETFLIX / "pattern.yaml").read_text(encoding="utf-8")
        + "\nmosaics:\n  small: {vectors: false}\n  big: {}\n",
        encoding="utf-8",
    )
    assert pattern_targets(pattern) == ["big", "small"]
