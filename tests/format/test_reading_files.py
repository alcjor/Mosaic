"""``conformance/reading/``: the Python reader judges each file as ``cases.json`` says (3.8).

The TypeScript kit reads the same files and ``cases.json`` (``kit/test/open.test.ts``), so the
two readers agree on what opens and why the rest is refused.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from mosaic_format.check import check_file
from mosaic_format.reader import FileRefusedError
from mosaic_format.reader import open as open_sealed

from tests.conftest import REPO

FILES = REPO / "conformance" / "reading"
CASES: dict[str, dict[str, object]] = json.loads((FILES / "cases.json").read_text("utf-8"))

MESSAGE = {
    "sqlite": "not a readable SQLite 3 database",
    "encoding": "text encoding UTF-16",
    "application_id": "application_id 0x",
    "user_version": "user_version ",
    "format_version": "format version ",
    "schema": "schema does not match format.sql",
    "header": "header ",
}
"""What the Python reader's message says for each rule of ``cases.json``."""


def _load() -> ModuleType:
    path = REPO / "scripts" / "make_reading_files.py"
    spec = importlib.util.spec_from_file_location("make_reading_files", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_reading_files"] = module
    spec.loader.exec_module(module)
    return module


mrf = _load()


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_reader_opens_or_refuses_each_file_as_cases_json_says(name: str) -> None:
    case = CASES[name]
    path = FILES / name
    if case["opens"]:
        with open_sealed(path) as sealed:
            assert dict(sealed.header) == case["header"]
        return
    with pytest.raises(FileRefusedError) as refused:
        open_sealed(path).close()
    message = str(refused.value)
    assert message.startswith(f"{path}: ")
    assert MESSAGE[str(case["rule"])] in message.removeprefix(f"{path}: ")


@pytest.mark.parametrize("name", sorted(CASES))
def test_mosaic_check_passes_the_files_that_open_and_fails_the_others(name: str) -> None:
    pieces = [FILES / mrf.PIECE] if name.endswith(".mosaic") else []
    report = check_file(FILES / name, pieces=pieces)
    assert report.ok is CASES[name]["opens"], [str(v) for v in report.violations]


def test_every_rule_has_a_file_and_both_kinds_open() -> None:
    assert {c["rule"] for c in CASES.values()} == {None, *mrf.RULES}
    opening = sorted(n for n, c in CASES.items() if c["opens"])
    assert opening == ["mosaic.mosaic", "stat4.mosaic", "tessera.tessera", "wal.mosaic"]
    for name in opening:
        assert CASES[name]["rule"] is None
        header = CASES[name]["header"]
        assert isinstance(header, dict)
        assert header["kind"] == name.rsplit(".", 1)[1]
    assert CASES["wal.mosaic"]["header"] == CASES["mosaic.mosaic"]["header"]
    assert CASES["stat4.mosaic"]["header"] == CASES["mosaic.mosaic"]["header"]


def test_the_utf_16_file_holds_the_conforming_mosaic_stored_as_utf_16() -> None:
    import sqlite3

    def rows(name: str, encoding: str) -> list[tuple[object, ...]]:
        uri = (FILES / name).resolve().as_uri() + "?mode=ro&immutable=1"
        con = sqlite3.connect(uri, uri=True)
        try:
            assert con.execute("PRAGMA encoding").fetchone() == (encoding,)
            return con.execute("SELECT * FROM v_node ORDER BY id").fetchall()
        finally:
            con.close()

    assert rows("utf-16.mosaic", "UTF-16le") == rows("mosaic.mosaic", "UTF-8")


def test_the_files_are_exactly_what_the_script_writes(tmp_path: Path) -> None:
    assert sorted(p.name for p in FILES.iterdir()) == sorted(mrf.outputs())
    mrf.write(tmp_path)
    for name in mrf.outputs():
        assert (tmp_path / name).read_bytes() == (FILES / name).read_bytes(), name


def test_the_readme_lists_every_file_with_its_rule() -> None:
    readme = (FILES / "README.md").read_text("utf-8")
    for name, case in CASES.items():
        row = next(line for line in readme.splitlines() if line.startswith(f"| `{name}` |"))
        assert ("opens" if case["opens"] else f"`{case['rule']}`") in row
