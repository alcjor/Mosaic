"""scripts/pr_sheet.py draws the overview sheet at the top of every PR body."""

import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.conftest import REPO

SVG = "{http://www.w3.org/2000/svg}"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pr_sheet", REPO / "scripts" / "pr_sheet.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pr_sheet = _load()

SHEET: dict[str, Any] = {
    "slice": "M1.3",
    "pr": 120,
    "title": "Split a column into linked things",
    "summary": "A CSV column becomes one node per distinct value, linked from its row.",
    "status": "ready",
    "question": {
        "section": "§4.2",
        "text": "Is an empty value after a separator a thing?",
        "readings": [
            {"name": "Skip it", "given": "'a,,b'", "observed": "two linked things, a and b"},
            {"name": "Keep it", "given": "'a,,b'", "observed": "three, one with an empty key"},
        ],
    },
    "map": {
        "spec": [{"id": "s", "label": "§4.2 Columns as things"}],
        "code": [{"id": "c", "label": "tessera/csv.py", "note": "+120 -14"}],
        "tests": [{"id": "t", "label": "test_csv_edges.py"}],
        "arrows": [["s", "c"], ["c", "t"]],
    },
    "done_when": [
        {"item": "Directors split on commas", "proof": "test_split_on_separator", "ok": True},
        {"item": "Same hash twice", "proof": "pytest -m slow", "ok": False},
    ],
    "rounds": [{"n": 1, "verifier": "6 tests, 1 fail", "reviewer": "BLOCKING 1"}],
    "verdict": "PASS",
    "assumptions": [{"decision": "Trim spaces", "section": "§4.2", "ruling": "accept"}],
    "numbers": [{"label": "tests", "value": "+6"}],
}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_sheet_is_well_formed_svg_with_nothing_loaded_from_outside(theme: str) -> None:
    svg = pr_sheet.render(SHEET, theme)
    root = ET.fromstring(svg)
    assert root.tag == f"{SVG}svg"
    names = {el.tag.removeprefix(SVG) for el in root.iter()}
    assert not names & {"script", "image", "foreignObject", "style", "use", "a"}
    assert re.findall(r"https?://[^\"']+", svg) == ["http://www.w3.org/2000/svg"]


def test_the_same_sheet_draws_the_same_bytes() -> None:
    copy = json.loads(json.dumps(SHEET))
    assert pr_sheet.render(SHEET, "light") == pr_sheet.render(copy, "light")


def test_every_arrow_gets_a_numbered_badge_in_order() -> None:
    root = ET.fromstring(pr_sheet.render(SHEET, "light"))
    badges = [el.text for el in root.iter(f"{SVG}text") if el.text and el.text.isdigit()]
    assert badges[:2] == ["1", "2"]


def test_text_is_escaped() -> None:
    sheet = {**SHEET, "title": '<b> & "quotes"'}
    root = ET.fromstring(pr_sheet.render(sheet, "light"))
    assert any(el.text == '<b> & "quotes"' for el in root.iter(f"{SVG}text"))


def test_an_arrow_to_a_missing_box_names_the_sheet_and_the_arrow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = {**SHEET, "map": {**SHEET["map"], "arrows": [["s", "nowhere"]]}}
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert pr_sheet.main([str(path), "--out", str(tmp_path / "out")]) == 1
    err = capsys.readouterr().err
    assert str(path) in err and "arrow 1" in err and "nowhere" in err


def test_main_writes_a_light_and_a_dark_file(tmp_path: Path) -> None:
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps(SHEET), encoding="utf-8")
    assert pr_sheet.main([str(path), "--out", str(tmp_path / "pr-sheet")]) == 0
    assert (tmp_path / "pr-sheet-light.svg").is_file()
    assert (tmp_path / "pr-sheet-dark.svg").is_file()


def test_long_words_wrap_inside_the_width() -> None:
    lines = pr_sheet.wrap("packages/mosaic-build/src/mosaic_build/mosaic/normalise.py", 13, 120)
    assert len(lines) > 1
    assert all(len(line) <= int(120 / (13 * 0.53)) for line in lines)
