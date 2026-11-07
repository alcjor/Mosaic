"""Edge cases of the expected-hashes files (Specification 0.1, section 11; plan M3.12).

Written from the spec and the plan's words, not from the implementation: a file that is not
the shape ``tests/fixtures/expected.py`` documents is an :class:`ExpectedError` that names the
file (never another exception), a build is compared field by field, and the slow Netflix test
fails whenever a hash, the model or the target differs from the file.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.conftest import REPO
from tests.fixtures import test_netflix
from tests.fixtures.expected import (
    FIELDS,
    FILE,
    Expected,
    ExpectedError,
    differences,
    load_expected,
    pattern_targets,
)

NETFLIX = REPO / "conformance" / "fixtures" / "netflix"
MODEL = "snowflake-arctic-embed-xs@" + "e" * 64
OTHER = "f" * 64


def _raw(directory: Path, content: bytes | str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    (directory / FILE).write_bytes(data)
    return directory


def _entry(**changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "knowledge_hash": "a" * 64,
        "vector_hash": "b" * 64,
        "embed_model": MODEL,
    }
    entry.update(changes)
    return entry


# --- untrusted or corrupt files (section 11: the maintainer owns the file; agents propose) ---


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"{",
        b"null",
        b"[]",
        b'"text"',
        b"42",
        b'{"mosaics": null}',
        b'{"mosaics": []}',
        b'{"mosaics": "default"}',
        b'{"mosaics": {"default": []}}',
        b'{"mosaics": {"default": null}}',
        b'{"mosaics": {"default": "a"}}',
        b"\xef\xbb\xbf" + b'{"mosaics": {}}',  # a byte order mark
        b'{"mosaics": {}} trailing',
        b'{"mosaics": {"default": {"knowledge_hash": NaN}}}',
    ],
)
def test_a_corrupt_file_is_an_expected_error_naming_the_file(
    tmp_path: Path, content: bytes
) -> None:
    fixture = _raw(tmp_path / "f", content)
    with pytest.raises(ExpectedError) as error:
        load_expected(fixture)
    assert str(fixture / FILE) in str(error.value)


def test_a_file_that_is_not_utf8_is_an_expected_error_naming_the_file(tmp_path: Path) -> None:
    fixture = _raw(tmp_path / "f", b'{"comment": "\xff\xfe", "mosaics": {}}')
    with pytest.raises(ExpectedError) as error:
        load_expected(fixture)
    assert str(fixture / FILE) in str(error.value)


def test_a_directory_in_place_of_the_file_is_an_expected_error(tmp_path: Path) -> None:
    (tmp_path / FILE).mkdir()
    with pytest.raises(ExpectedError, match=FILE):
        load_expected(tmp_path)


def test_a_file_with_a_nul_byte_is_an_expected_error(tmp_path: Path) -> None:
    fixture = _raw(tmp_path / "f", b'{"mosaics": {}}\x00')
    with pytest.raises(ExpectedError, match=FILE):
        load_expected(fixture)


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        True,
        ["a" * 64],
        "a" * 64 + "\n",
        " " + "a" * 64,
        "a" * 65,
        "a" * 32,
        "",
        "sha256:" + "a" * 64,
        "A" * 64,
        "g" * 64,
        "\uff41" * 64,  # full-width letters that look like hex
        "\u0660" * 64,  # Arabic-Indic digits
    ],
)
def test_a_knowledge_hash_that_is_not_64_lowercase_hex_is_rejected(
    tmp_path: Path, value: object
) -> None:
    fixture = _raw(
        tmp_path / "f", json.dumps({"mosaics": {"default": _entry(knowledge_hash=value)}})
    )
    with pytest.raises(ExpectedError, match="knowledge_hash"):
        load_expected(fixture)


@pytest.mark.parametrize(
    "value", [0, False, "", "b" * 63, "b" * 64 + "\n", "B" * 64, ["b" * 64], "٢" * 64]
)
def test_a_vector_hash_that_is_not_64_lowercase_hex_or_null_is_rejected(
    tmp_path: Path, value: object
) -> None:
    fixture = _raw(tmp_path / "f", json.dumps({"mosaics": {"default": _entry(vector_hash=value)}}))
    with pytest.raises(ExpectedError, match="vector_hash"):
        load_expected(fixture)


@pytest.mark.parametrize(
    "value",
    [
        0,
        "",
        "@" + "e" * 64,
        "name@",
        "name@" + "e" * 63,
        "name@" + "E" * 64,
        "name@" + "e" * 64 + "\n",
        "na me@" + "e" * 64,
        "a@b@" + "e" * 64,
        "name " + "e" * 64,
        ["name@" + "e" * 64],
    ],
)
def test_an_embed_model_that_is_not_name_at_hash_or_null_is_rejected(
    tmp_path: Path, value: object
) -> None:
    fixture = _raw(tmp_path / "f", json.dumps({"mosaics": {"default": _entry(embed_model=value)}}))
    with pytest.raises(ExpectedError, match="embed_model"):
        load_expected(fixture)


@pytest.mark.parametrize("missing", FIELDS)
def test_an_entry_missing_one_field_is_rejected_even_when_the_others_are_valid(
    tmp_path: Path, missing: str
) -> None:
    entry = _entry()
    del entry[missing]
    fixture = _raw(tmp_path / "f", json.dumps({"mosaics": {"default": entry}}))
    with pytest.raises(ExpectedError, match="default"):
        load_expected(fixture)


def test_one_bad_target_among_good_ones_rejects_the_file_and_names_the_target(
    tmp_path: Path,
) -> None:
    data = {"mosaics": {"good": _entry(), "bad": _entry(knowledge_hash="x"), "fine": _entry()}}
    fixture = _raw(tmp_path / "f", json.dumps(data))
    with pytest.raises(ExpectedError, match="bad"):
        load_expected(fixture)


def test_a_comment_of_any_json_type_is_ignored(tmp_path: Path) -> None:
    for comment in (None, 1, ["x"], {"a": 1}, "é\u0000"):
        fixture = _raw(
            tmp_path / "f", json.dumps({"comment": comment, "mosaics": {"default": _entry()}})
        )
        assert set(load_expected(fixture)) == {"default"}


def test_a_target_name_is_kept_as_written_and_is_case_sensitive(tmp_path: Path) -> None:
    data = {"mosaics": {"Default": _entry(knowledge_hash="1" * 64), "default": _entry()}}
    expected = load_expected(_raw(tmp_path / "f", json.dumps(data)))
    assert sorted(expected) == ["Default", "default"]
    assert expected["Default"].knowledge_hash == "1" * 64
    found = differences(
        {"default": expected["default"]},
        "Default",
        knowledge_hash="a" * 64,
        vector_hash="b" * 64,
        embed_model=MODEL,
    )
    assert len(found) == 1 and "no entry" in found[0]


def test_targets_are_read_in_utf8_byte_order(tmp_path: Path) -> None:
    names = ["é", "b", "a", "B", "\U0001f600", "￮"]
    data = {"mosaics": {n: _entry() for n in names}}
    assert list(load_expected(_raw(tmp_path / "f", json.dumps(data)))) == sorted(
        names, key=lambda s: s.encode("utf-8")
    )


def test_reading_the_same_file_twice_gives_equal_values(tmp_path: Path) -> None:
    fixture = _raw(tmp_path / "f", json.dumps({"mosaics": {"default": _entry()}}))
    assert load_expected(fixture) == load_expected(fixture)


# --- comparing a build with the file ----------------------------------------------------------


def test_all_three_fields_differing_are_all_reported_in_a_fixed_order() -> None:
    expected = {"default": Expected("a" * 64, "b" * 64, MODEL)}
    kwargs = {"knowledge_hash": "1" * 64, "vector_hash": "2" * 64, "embed_model": "m@" + "3" * 64}
    found = differences(expected, "default", **kwargs)
    assert [line.split(":")[0] for line in found] == [f"default.{f}" for f in FIELDS]
    assert found == differences(expected, "default", **kwargs)


def test_a_build_with_vectors_where_none_are_expected_is_a_difference() -> None:
    expected = {"small": Expected("a" * 64, None, None)}
    found = differences(
        expected, "small", knowledge_hash="a" * 64, vector_hash="b" * 64, embed_model=MODEL
    )
    assert {line.split(":")[0] for line in found} == {"small.vector_hash", "small.embed_model"}


def test_a_hash_that_differs_only_in_case_is_a_difference() -> None:
    expected = {"default": Expected("a" * 64, None, None)}
    assert differences(
        expected, "default", knowledge_hash="A" * 64, vector_hash=None, embed_model=None
    )


def test_a_hash_that_differs_in_its_last_character_is_a_difference() -> None:
    expected = {"default": Expected("a" * 63 + "0", None, None)}
    assert differences(
        expected, "default", knowledge_hash="a" * 63 + "1", vector_hash=None, embed_model=None
    )


def test_an_empty_expected_set_has_no_entry_for_any_target() -> None:
    found = differences({}, "default", knowledge_hash="a" * 64, vector_hash=None, embed_model=None)
    assert found == [f"{FILE} has no entry for target `default`"]


def test_only_the_named_target_is_compared() -> None:
    expected = {"a": Expected("1" * 64, None, None), "b": Expected("2" * 64, None, None)}
    assert (
        differences(expected, "b", knowledge_hash="2" * 64, vector_hash=None, embed_model=None)
        == []
    )


# --- pattern targets (section 5.4) ------------------------------------------------------------


@pytest.mark.parametrize("mosaics", ["{}", "[]", "null", "~", "x", "[a, b]"])
def test_a_pattern_whose_mosaics_names_no_target_has_the_default_target(
    tmp_path: Path, mosaics: str
) -> None:
    pattern = tmp_path / "pattern.yaml"
    pattern.write_text(f"pieces: [a@{'0' * 64}]\nmosaics: {mosaics}\n", encoding="utf-8")
    assert pattern_targets(pattern) == ["default"]


def test_pattern_targets_are_listed_in_one_order_however_the_pattern_orders_them(
    tmp_path: Path,
) -> None:
    one, two = tmp_path / "one.yaml", tmp_path / "two.yaml"
    one.write_text("mosaics:\n  b: {}\n  a: {}\n  c: {}\n", encoding="utf-8")
    two.write_text("mosaics:\n  c: {}\n  a: {}\n  b: {}\n", encoding="utf-8")
    assert pattern_targets(one) == pattern_targets(two) == ["a", "b", "c"]


# --- the Netflix slow test fails on anything that differs -------------------------------------


def _good_run() -> test_netflix.Run:
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


@pytest.mark.parametrize(
    "change",
    [
        {"embed_model": "snowflake-arctic-embed-xs@" + OTHER},
        {"embed_model": None},
        {"vector_hash": None},
        {"vector_hash": None, "embed_model": None},
        {"mosaic_hash": OTHER},
        {"mosaic_hash": ""},
    ],
)
@pytest.mark.parametrize("which", [0, 1])
def test_the_netflix_slow_test_fails_when_either_run_differs_in_any_field(
    change: dict[str, str | None], which: int
) -> None:
    good = _good_run()
    runs = [good, good]
    runs[which] = replace(good, **change)
    with pytest.raises(AssertionError):
        test_netflix.test_each_build_has_the_expected_hashes((runs[0], runs[1]))


def test_the_netflix_slow_test_fails_when_the_expected_file_lacks_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _raw(tmp_path / "n", json.dumps({"mosaics": {"other": _entry()}}))
    monkeypatch.setattr(test_netflix, "FIXTURE", fixture)
    run = _good_run()
    with pytest.raises(AssertionError, match="no entry"):
        test_netflix.test_each_build_has_the_expected_hashes((run, run))


def test_the_netflix_slow_test_fails_when_the_expected_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(test_netflix, "FIXTURE", tmp_path)
    run = _good_run()
    with pytest.raises(ExpectedError):
        test_netflix.test_each_build_has_the_expected_hashes((run, run))


def test_the_netflix_slow_test_fails_when_the_expected_vector_hash_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _good_run()
    data = json.loads((NETFLIX / FILE).read_text(encoding="utf-8"))
    data["mosaics"][test_netflix.TARGET]["vector_hash"] = OTHER
    monkeypatch.setattr(test_netflix, "FIXTURE", _raw(tmp_path / "n", json.dumps(data)))
    with pytest.raises(AssertionError, match="vector_hash"):
        test_netflix.test_each_build_has_the_expected_hashes((run, run))


def test_the_netflix_file_pins_a_vector_hash_different_from_the_knowledge_hash() -> None:
    # Sections 3.6 and 3.7 hash different things: equal values would be a copy-paste slip.
    entry = load_expected(NETFLIX)[test_netflix.TARGET]
    assert entry.knowledge_hash != entry.vector_hash


def test_the_netflix_expected_file_is_utf8_with_no_bom_and_ends_with_a_newline() -> None:
    raw = (NETFLIX / FILE).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw  # LF only (.gitattributes)
    raw.decode("utf-8")
