"""A tessera's notice, set in its import settings (plan M3.14; sections 3.2, 4.1, 7.2, 10).

The maintainer's answer on #125: the Chinook mosaic carries its source's MIT notice, named in the
import settings. ``mosaic import csv`` and ``mosaic import sqlite`` read an optional ``notice``
setting. The tessera's one source row has that notice and ``header.settings`` records it. Without
it the notice is NULL and the tessera is as before. A mosaic built from such a tessera copies the
source row with its notice (section 3.2), and the build report lists it (section 7.2).
"""

import json
import re
import sqlite3
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build.cli import main
from mosaic_build.tessera import csv, sqlite

NOTICE = "Invented Data. Copyright (c) 2026 Ada Quill. MIT License."

CSV_SETTINGS = """\
type: Thing
key: id
label: name
props: [name]
"""

SQLITE_SETTINGS = """\
tables:
  Thing:
    label: name
    props: [name]
"""


def _csv(directory: Path) -> Path:
    path = directory / "things.csv"
    path.write_text("id,name\n1,Alpha\n2,Beta\n", encoding="utf-8")
    return path


def _db(directory: Path) -> Path:
    path = directory / "things.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE Thing (id INTEGER PRIMARY KEY, name TEXT);"
        "INSERT INTO Thing VALUES (1, 'Alpha'), (2, 'Beta');"
    )
    con.commit()
    con.close()
    return path


KINDS = {
    "csv": (_csv, CSV_SETTINGS),
    "sqlite": (_db, SQLITE_SETTINGS),
}


def _import(tmp_path: Path, kind: str, settings: str) -> tuple[int, Path]:
    make, _ = KINDS[kind]
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = make(tmp_path)
    path = tmp_path / "settings.yaml"
    path.write_text(settings, encoding="utf-8")
    out = tmp_path / "pieces" / "things.tessera"
    rc = main(["import", kind, str(source), "--settings", str(path), "-o", str(out)])
    return rc, out


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with mosaic_format.open(path) as f:
        return f.query(sql)


def _with_notice(settings: str, notice: str = json.dumps(NOTICE)) -> str:
    return f"notice: {notice}\n" + settings


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_notice_setting_is_the_notice_of_the_one_source_row(tmp_path: Path, kind: str) -> None:
    rc, out = _import(tmp_path, kind, _with_notice(KINDS[kind][1]))
    assert rc == 0
    assert _rows(out, "SELECT notice FROM source") == [(NOTICE,)]


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_header_settings_record_the_notice(tmp_path: Path, kind: str) -> None:
    _, out = _import(tmp_path, kind, _with_notice(KINDS[kind][1]))
    ((settings,),) = _rows(out, "SELECT settings FROM header")
    assert json.loads(str(settings))["notice"] == NOTICE


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_header_settings_as_a_settings_file_give_the_same_tessera(
    tmp_path: Path, kind: str
) -> None:
    _, first = _import(tmp_path / "a", kind, _with_notice(KINDS[kind][1]))
    ((settings,),) = _rows(first, "SELECT settings FROM header")
    _, second = _import(tmp_path / "b", kind, str(settings))
    with mosaic_format.open(first) as a, mosaic_format.open(second) as b:
        assert a.knowledge_hash == b.knowledge_hash


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_without_a_notice_the_notice_is_null_and_the_settings_do_not_name_it(
    tmp_path: Path, kind: str
) -> None:
    _, out = _import(tmp_path, kind, KINDS[kind][1])
    assert _rows(out, "SELECT notice FROM source") == [(None,)]
    ((settings,),) = _rows(out, "SELECT settings FROM header")
    assert "notice" not in json.loads(str(settings))


def test_without_a_notice_the_settings_json_is_as_before() -> None:
    """A tessera without a notice keeps its hash: header.settings has no new key."""
    assert "notice" not in json.loads(csv.Settings().as_json())
    assert "notice" not in json.loads(sqlite.Settings().as_json())


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_notice_changes_the_knowledge_hash(tmp_path: Path, kind: str) -> None:
    _, plain = _import(tmp_path / "a", kind, KINDS[kind][1])
    _, noticed = _import(tmp_path / "b", kind, _with_notice(KINDS[kind][1]))
    with mosaic_format.open(plain) as a, mosaic_format.open(noticed) as b:
        assert a.knowledge_hash != b.knowledge_hash


def test_a_notice_keeps_its_text_as_written(tmp_path: Path) -> None:
    notice = "Données inventées.\nLigne deux, avec  deux espaces."
    _, out = _import(tmp_path, "csv", _with_notice(CSV_SETTINGS, json.dumps(notice)))
    assert _rows(out, "SELECT notice FROM source") == [(notice,)]


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("5", "notice must be text"),
        ("[a]", "notice must be text"),
        ("null", "notice must be text"),
        ('""', "notice is empty"),
        ('"a\\u0000b"', "U\\+0000"),
    ],
)
def test_a_notice_that_is_not_text_is_empty_or_holds_nul_names_the_file_and_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str, value: str, match: str
) -> None:
    rc, out = _import(tmp_path, kind, KINDS[kind][1] + f"notice: {value}\n")
    assert rc == 1
    err = capsys.readouterr().err
    assert "settings.yaml:5: " in err, err
    assert "notice" in err
    assert re.search(match, err), err
    assert not out.exists()


# --- the mosaic carries it (sections 3.2, 7.2) ----------------------------------------------


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_mosaic_built_from_the_tessera_carries_the_notice(tmp_path: Path, kind: str) -> None:
    _, tessera = _import(tmp_path, kind, _with_notice(KINDS[kind][1]))
    with mosaic_format.open(tessera) as t:
        piece = t.knowledge_hash
    pattern = tmp_path / "pattern.yaml"
    pattern.write_text(
        'format: "0.1"\n'
        f"pieces:\n  - things@{piece}\n"
        "types:\n"
        "  Thing:\n"
        "    key: id\n"
        "    describe: An invented thing\n"
        "    from:\n"
        "      things.Thing: {id: key}\n"
        "mosaics:\n  small: {vectors: false}\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    args = ["build", str(pattern), "--target", "small", "--pieces", str(tessera.parent)]
    assert main([*args, "-o", str(out)]) == 0
    source = "things.csv" if kind == "csv" else "things.db"
    assert _rows(out / "small.mosaic", "SELECT id, notice FROM source ORDER BY id") == [
        ("things", None),
        (f"things/{source}", NOTICE),
    ]
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    assert report["notices"] == [{"piece": "things", "text": NOTICE}]


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_import_help_documents_the_notice(capsys: pytest.CaptureFixture[str], kind: str) -> None:
    with pytest.raises(SystemExit):
        main(["import", kind, "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "notice" in text and "licence or confidentiality marking" in text
