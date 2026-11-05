"""Step 1 of a build: check, resolve and open (Specification 0.1, section 7.1 step 1, 5.1, 5.6).

Any failure stops the build: a pattern or proposals file that breaks section 5 with
``invalid_input``; a piece whose hash matches no available file or more than one with
``piece_mismatch`` (section 5.1); an available file the reading rules refuse with
``invalid_input`` (section 3.8).
"""

import json
import shutil
from pathlib import Path

import pytest
from mosaic_build.mosaic import BuildError, check

from tests.mosaic.pieces import node, pattern, tessera

TYPES = {"Gauge": {"key": "tag", "from": {"list.Row": {"tag": "key"}}}}


@pytest.fixture
def piece(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "list.tessera"
    return path, tessera(path, [node("Row:1", "G-1")])


def test_resolves_a_piece_by_a_hash_prefix_and_opens_it(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    path, h = piece
    with check(pattern(tmp_path, [f"list@{h[:8]}"], TYPES), pieces=[path]) as inputs:
        (p,) = inputs.pieces
        assert (p.name, p.rank, p.kind, p.knowledge_hash) == ("list", 0, "tessera", h)
        assert p.file.query("SELECT id FROM node") == [("Row:1",)]


def test_a_piece_path_is_available_relative_to_the_pattern(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    _, h = piece
    sub = tmp_path / "patterns"
    sub.mkdir()
    entry = {"name": "list", "hash": h, "kind": "tessera", "path": "../list.tessera"}
    with check(pattern(sub, [entry], TYPES)) as inputs:
        assert inputs.piece("list").path == "../list.tessera"


def test_a_piece_that_matches_no_file_fails_with_piece_mismatch(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    path, _ = piece
    with pytest.raises(BuildError) as e:
        check(pattern(tmp_path, ["list@" + "0" * 12], TYPES), pieces=[path])
    assert e.value.reason == "piece_mismatch"
    assert "list@000000000000 matches no available file" in str(e.value)


def test_a_piece_that_matches_two_files_fails_with_piece_mismatch(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    path, h = piece
    copy = tmp_path / "copy.tessera"
    shutil.copyfile(path, copy)
    with pytest.raises(BuildError) as e:
        check(pattern(tmp_path, [f"list@{h[:8]}"], TYPES), pieces=[path, copy])
    assert e.value.reason == "piece_mismatch"
    assert "matches 2 files" in str(e.value)


def test_the_same_file_given_twice_is_one_file(tmp_path: Path, piece: tuple[Path, str]) -> None:
    path, h = piece
    with check(pattern(tmp_path, [f"list@{h}"], TYPES), pieces=[path, path]) as inputs:
        assert [p.name for p in inputs.pieces] == ["list"]


def test_a_piece_of_another_kind_than_the_pattern_says_fails_with_piece_mismatch(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    path, h = piece
    entry = {"name": "list", "hash": h, "kind": "mosaic"}
    with pytest.raises(BuildError) as e:
        check(pattern(tmp_path, [entry], TYPES), pieces=[path])
    assert e.value.reason == "piece_mismatch"
    assert "is a mosaic in the pattern" in str(e.value)


def test_an_invalid_pattern_fails_with_invalid_input(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    path, h = piece
    types = {"Gauge": {"key": "tag", "from": {"list.Row": {"tag": "key"}}, "colour": "red"}}
    with pytest.raises(BuildError) as e:
        check(pattern(tmp_path, [f"list@{h}"], types), pieces=[path])
    assert e.value.reason == "invalid_input"
    assert "schema" in str(e.value)


def test_a_from_type_the_piece_does_not_declare_fails_with_invalid_input(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    path, h = piece
    types = {"Gauge": {"key": "tag", "from": {"list.Line": {"tag": "key"}}}}
    with pytest.raises(BuildError) as e:
        check(pattern(tmp_path, [f"list@{h}"], types), pieces=[path])
    assert e.value.reason == "invalid_input"
    assert "from-type" in str(e.value)


def test_a_file_the_reading_rules_refuse_fails_with_invalid_input(
    tmp_path: Path, piece: tuple[Path, str]
) -> None:
    path, h = piece
    junk = tmp_path / "junk.tessera"
    junk.write_bytes(b"not a database at all" * 100)
    with pytest.raises(BuildError) as e:
        check(pattern(tmp_path, [f"list@{h}"], TYPES), pieces=[path, junk])
    assert e.value.reason == "invalid_input"
    assert "junk.tessera" in str(e.value)


def test_invalid_proposals_fail_with_invalid_input(tmp_path: Path, piece: tuple[Path, str]) -> None:
    path, h = piece
    proposals = tmp_path / "proposals.yaml"
    proposals.write_text(json.dumps({"format": "0.1", "proposals": []}), encoding="utf-8")
    with pytest.raises(BuildError) as e:
        check(pattern(tmp_path, [f"list@{h}"], TYPES), pieces=[path], proposals=proposals)
    assert e.value.reason == "invalid_input"


def test_valid_proposals_are_read(tmp_path: Path, piece: tuple[Path, str]) -> None:
    path, h = piece
    proposals = tmp_path / "proposals.yaml"
    data = {"format": "0.1", "built_from": "0" * 64, "proposals": []}
    proposals.write_text(json.dumps(data), encoding="utf-8")
    with check(
        pattern(tmp_path, [f"list@{h}"], TYPES), pieces=[path], proposals=proposals
    ) as inputs:
        assert inputs.proposals == data


def test_a_missing_file_is_named(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"nowhere\.tessera"):
        check(pattern(tmp_path, ["list@" + "0" * 8], TYPES), pieces=[tmp_path / "nowhere.tessera"])
