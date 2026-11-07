"""Edge cases of the Chinook mosaic's MIT notice (Specification 0.1, sections 3.2 to 3.9, 10).

Written by the verifier from the spec's words and the maintainer's answer on #125 ("It carries the
notice"), without reading the implementation. Like ``test_chinook_edges.py`` these are ``slow``:
they import the pinned source and build ``conformance/fixtures/chinook/pattern.yaml``.

Sections: 3.2 (mosaic ``source`` rows copy the notice), 3.6 (the notice is hashed, so the pin
holds it), 3.9 (checker: notices of every piece carried), 5.1 (pins), 7.2 (report ``notices``),
10 (notices travel with the mosaic).
"""

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from mosaic_format.reader import Limits
from mosaic_format.reader import open as open_sealed

from tests.fixtures.expected import load_expected
from tests.fixtures.test_chinook_edges import (
    FIXTURE,
    MANIFEST,
    SOURCE,
    Built,
    _import,
    _mosaic,
    _no_vectors_pattern,
    _ok,
    _pinned,
)

NOTICE = "Chinook Database. Copyright (c) 2008-2024 Luis Rocha. MIT License."
ALL_ROWS = Limits(seconds=None, rows=None)

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    """The fixture's flow once, with vectors off (the knowledge hash does not depend on them)."""
    directory = tmp_path_factory.mktemp("chinook-notice")
    pieces, out = directory / "pieces", directory / "out"
    pieces.mkdir()
    shutil.copyfile(SOURCE, directory / SOURCE.name)
    tessera = _import(directory, pieces)
    _ok(
        "build",
        _no_vectors_pattern(directory),
        "--pieces",
        pieces,
        "-o",
        out,
        cwd=directory,
    )
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    return Built(directory, pieces, tessera, out / "default.mosaic", report)


def _settings_with(directory: Path, notice_line: str | None) -> Path:
    """The fixture's settings with its notice line replaced (or removed with ``None``)."""
    lines = (FIXTURE / "settings.yaml").read_text(encoding="utf-8").splitlines()
    [at] = [i for i, line in enumerate(lines) if line.startswith("notice:")]
    if notice_line is None:
        del lines[at]
    else:
        lines[at] = notice_line
    path = directory / "settings.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _import_with(directory: Path, settings: Path, name: str) -> Path:
    shutil.copyfile(SOURCE, directory / SOURCE.name)
    out = directory / f"{name}.tessera"
    _ok("import", "sqlite", SOURCE.name, "--settings", settings, "-o", out, cwd=directory)
    return out


def _tessera_hash(path: Path) -> str:
    with open_sealed(path, limits=ALL_ROWS) as t:
        return t.knowledge_hash


def test_the_tessera_source_row_holds_the_notice_exactly(built: Built) -> None:
    # 3.2, 10: the one source row of the tessera carries the notice, no more and no less.
    with open_sealed(built.tessera, limits=ALL_ROWS) as t:
        assert t.query("SELECT id, kind, notice FROM source", limits=ALL_ROWS) == [
            ("Chinook_Sqlite.sqlite", "database", NOTICE)
        ]


def test_the_notice_names_the_licence_and_holder_the_manifest_records() -> None:
    # 10: the markings of the source are not lost; the manifest is the record of the licence.
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    [entry] = [f for f in manifest["fixtures"] if f["name"] == "chinook"]
    assert entry["licence"].startswith("MIT (")
    holder = entry["licence"].split("(", 1)[1].split(";", 1)[0].rstrip(")")
    assert holder == "Copyright (c) 2008-2024 Luis Rocha"
    settings = (FIXTURE / "settings.yaml").read_text(encoding="utf-8")
    assert holder in settings
    assert "MIT" in settings


def test_the_mosaic_source_row_copies_the_tessera_notice_byte_for_byte(built: Built) -> None:
    # 3.2: every original source of the piece is copied with its notice, id prefixed.
    with open_sealed(built.tessera, limits=ALL_ROWS) as t:
        [(sid, kind, hash_, notice)] = t.query(
            "SELECT id, kind, hash, notice FROM source", limits=ALL_ROWS
        )
    with built.open() as m:
        rows = m.query(
            "SELECT id, kind, hash, notice FROM source WHERE id LIKE 'chinook/%'",
            limits=ALL_ROWS,
        )
    assert rows == [(f"chinook/{sid}", kind, hash_, notice)]
    assert str(rows[0][3]).encode("utf-8") == NOTICE.encode("utf-8")


def test_only_the_original_source_carries_a_notice_in_the_mosaic(built: Built) -> None:
    # 3.2: the piece's own row (kind tessera) keeps its NULL; no other row invents a notice.
    with built.open() as m:
        rows = m.query("SELECT id, kind, notice FROM source ORDER BY id", limits=ALL_ROWS)
    assert rows == [
        ("chinook", "tessera", None),
        ("chinook/Chinook_Sqlite.sqlite", "database", NOTICE),
    ]


def test_the_report_lists_the_notice_once_with_its_piece(built: Built) -> None:
    # 7.2: one entry per distinct piece name and notice text.
    assert built.report["notices"] == [{"piece": "chinook", "text": NOTICE}]


def test_the_mosaic_with_the_notice_passes_the_checker_with_its_pieces(built: Built) -> None:
    # 3.9: notices of every piece carried, verified for the pieces given.
    _ok("check", built.mosaic, "--pieces", built.pieces, cwd=built.directory)
    _ok("check", built.mosaic, cwd=built.directory)


def test_the_notice_is_part_of_the_pinned_tessera_hash(tmp_path: Path) -> None:
    # 3.6, 5.1: without the notice the tessera is another tessera than the pattern pins.
    _, pinned = _pinned()
    with_notice = _import_with(tmp_path, _settings_with(tmp_path, f'notice: "{NOTICE}"'), "with")
    without = _import_with(tmp_path, _settings_with(tmp_path, None), "without")
    assert _tessera_hash(with_notice) == pinned
    assert _tessera_hash(without) != pinned


def test_a_notice_cut_short_gives_a_tessera_the_pattern_does_not_pin(tmp_path: Path) -> None:
    # 3.6, 5.1: the permission-less copyright line alone is a different notice, a different hash.
    _, pinned = _pinned()
    short = 'notice: "Chinook Database. Copyright (c) 2008-2024 Luis Rocha."'
    tessera = _import_with(tmp_path, _settings_with(tmp_path, short), "short")
    assert _tessera_hash(tessera) != pinned


def test_building_from_a_tessera_with_another_notice_is_a_piece_mismatch(tmp_path: Path) -> None:
    # 5.1, 7.2: the pin names the noticed tessera; a tessera that lost its notice is refused.
    name, _ = _pinned()
    pieces, out = tmp_path / "pieces", tmp_path / "out"
    pieces.mkdir()
    plain = _import_with(tmp_path, _settings_with(tmp_path, None), "plain")
    shutil.copyfile(plain, pieces / f"{name}.tessera")
    pattern = _no_vectors_pattern(tmp_path)
    done = _mosaic("build", pattern, "--pieces", pieces, "-o", out, cwd=tmp_path)
    assert done.returncode != 0
    assert not (out / "default.mosaic").exists()
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    assert report["outcome"] == "failed"
    assert report["reason"] == "piece_mismatch"


def test_a_mosaic_built_from_the_plain_tessera_has_another_knowledge_hash(tmp_path: Path) -> None:
    # 3.6, 7.1: the notice is hashed in the mosaic too, so dropping it is visible in the hash.
    name, _ = _pinned()
    pieces, out = tmp_path / "pieces", tmp_path / "out"
    pieces.mkdir()
    plain = _import_with(tmp_path, _settings_with(tmp_path, None), "plain")
    shutil.copyfile(plain, pieces / f"{name}.tessera")
    pinned_plain = _tessera_hash(plain)
    pattern = _no_vectors_pattern(tmp_path, piece_pin=pinned_plain)
    _ok("build", pattern, "--pieces", pieces, "-o", out, cwd=tmp_path)
    with open_sealed(out / "default.mosaic", limits=ALL_ROWS) as m:
        assert m.knowledge_hash != load_expected(FIXTURE)["default"].knowledge_hash
        assert m.query("SELECT notice FROM source WHERE notice IS NOT NULL", limits=ALL_ROWS) == []
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    assert report["notices"] == []


def _tamper(built: Built, tmp_path: Path, sql: str) -> Path:
    copy = tmp_path / "tampered.mosaic"
    shutil.copyfile(built.mosaic, copy)
    db = sqlite3.connect(copy)
    try:
        db.execute(sql)
        db.commit()
    finally:
        db.close()
    return copy


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE source SET notice = NULL WHERE kind = 'database'",
        "UPDATE source SET notice = 'MIT' WHERE kind = 'database'",
        "UPDATE source SET notice = notice || ' ' WHERE kind = 'database'",
    ],
    ids=["dropped", "changed", "padded"],
)
def test_a_mosaic_whose_notice_was_dropped_or_changed_fails_the_checker(
    built: Built, tmp_path: Path, sql: str
) -> None:
    # 3.9, invariant 15: notices of every piece are carried with the same text, or the file fails.
    copy = _tamper(built, tmp_path, sql)
    for extra in ([], ["--pieces", built.pieces]):
        done: subprocess.CompletedProcess[str] = _mosaic("check", copy, *extra, cwd=tmp_path)
        assert done.returncode != 0, done.stdout


def test_the_notice_text_appears_nowhere_else_in_the_mosaic(built: Built) -> None:
    # 10, 3.2: a marking lives in `source`; it is not copied into node, edge or evidence rows.
    with built.open() as m:
        assert m.query(
            "SELECT count(*) FROM source WHERE notice = ?", (NOTICE,), limits=ALL_ROWS
        ) == [(1,)]
        assert m.query(
            "SELECT count(*) FROM v_node WHERE label LIKE '%MIT License%'", limits=ALL_ROWS
        ) == [(0,)]
