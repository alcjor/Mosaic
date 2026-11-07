"""Edge cases of the import ``notice`` setting (plan M3.14; sections 3.1, 3.2, 3.6, 4.1, 7.2, 10).

Written from the spec's words and the slice's "Done when": the tessera's one source row holds
the notice and ``header.settings`` records it; a notice that is not text, is empty or holds
U+0000 is an error naming the file, the line and the setting (exit 1, no tessera); a mosaic
carries the notice in its copy of the source row and in the build report's ``notices``.
"""

import json
import re
import sqlite3
from pathlib import Path

import mosaic_format
import pytest
from mosaic_build.cli import main

CSV_SETTINGS = "type: Thing\nkey: id\nlabel: name\nprops: [name]\n"
SQLITE_SETTINGS = "tables:\n  Thing:\n    label: name\n    props: [name]\n"


def _csv(directory: Path) -> Path:
    path = directory / "things.csv"
    path.write_text("id,name\n1,Alpha\n2,Beta\n", encoding="utf-8")
    return path


def _db(directory: Path) -> Path:
    path = directory / "things.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE Thing (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE Other (id INTEGER PRIMARY KEY, name TEXT);"
        "INSERT INTO Thing VALUES (1, 'Alpha'), (2, 'Beta');"
        "INSERT INTO Other VALUES (1, 'Gamma');"
    )
    con.commit()
    con.close()
    return path


KINDS = {"csv": (_csv, CSV_SETTINGS), "sqlite": (_db, SQLITE_SETTINGS)}
BOTH = sorted(KINDS)


def _import(directory: Path, kind: str, settings: str | bytes, name: str = "things") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    make, _ = KINDS[kind]
    source = make(directory)
    path = directory / "settings.yaml"
    path.write_bytes(settings if isinstance(settings, bytes) else settings.encode("utf-8"))
    out = directory / "pieces" / f"{name}.tessera"
    rc = main(["import", kind, str(source), "--settings", str(path), "-o", str(out)])
    assert rc == 0
    return out


def _refuse(
    directory: Path, kind: str, settings: str | bytes, capsys: pytest.CaptureFixture[str]
) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    make, _ = KINDS[kind]
    source = make(directory)
    path = directory / "settings.yaml"
    path.write_bytes(settings if isinstance(settings, bytes) else settings.encode("utf-8"))
    out = directory / "pieces" / "things.tessera"
    rc = main(["import", kind, str(source), "--settings", str(path), "-o", str(out)])
    captured = capsys.readouterr()
    assert rc == 1, captured.err
    assert captured.out == "", captured.out
    assert "Traceback" not in captured.err, captured.err
    assert not out.exists()
    return captured.err


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with mosaic_format.open(path) as f:
        return f.query(sql)


def _hash(path: Path) -> str:
    with mosaic_format.open(path) as f:
        return f.knowledge_hash


def _quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a YAML double-quoted scalar


# --- values that are not text, empty or hold U+0000 (Done when 2; section 3.1) ------------------


@pytest.mark.parametrize("kind", BOTH)
@pytest.mark.parametrize(
    "value",
    ["true", "false", "1.5", "2026", "{a: 1}", "[]", "~", "{}", "0", "-1", ".inf", "[a, b]"],
)
def test_a_notice_of_another_kind_than_text_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str, value: str
) -> None:
    # Done when 2: "a notice that is not text". An unquoted 2026 or true is a number or a boolean.
    err = _refuse(tmp_path, kind, KINDS[kind][1] + f"notice: {value}\n", capsys)
    assert "settings.yaml:5: " in err, err
    assert "notice" in err


@pytest.mark.parametrize("kind", BOTH)
@pytest.mark.parametrize("value", ['"2026"', '"true"', '"null"', '"0"'])
def test_a_quoted_scalar_that_looks_like_another_kind_is_text(
    tmp_path: Path, kind: str, value: str
) -> None:
    # Done when 1: text is text however it reads.
    out = _import(tmp_path, kind, KINDS[kind][1] + f"notice: {value}\n")
    assert _rows(out, "SELECT notice FROM source") == [(json.loads(value),)]


@pytest.mark.parametrize("kind", BOTH)
def test_a_nul_written_as_a_yaml_zero_escape_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # Section 3.1: text MUST NOT contain U+0000 (YAML's \0 escape is U+0000 too).
    err = _refuse(tmp_path, kind, KINDS[kind][1] + 'notice: "a\\0b"\n', capsys)
    assert "settings.yaml:5: " in err and "notice" in err and "U+0000" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_nul_in_a_block_scalar_is_an_error_naming_the_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    err = _refuse(tmp_path, kind, KINDS[kind][1] + 'notice: "line one\\nline two\\u0000"\n', capsys)
    assert "notice" in err and "U+0000" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_nul_alone_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    err = _refuse(tmp_path, kind, KINDS[kind][1] + 'notice: "\\u0000"\n', capsys)
    assert "notice" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_notice_with_an_unpaired_surrogate_is_an_error_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # Section 3.1: header.settings is I-JSON (no unpaired surrogates), so the notice cannot be
    # recorded; the refusal is an error naming the file, never a traceback.
    err = _refuse(tmp_path, kind, KINDS[kind][1] + 'notice: "a\\uD800b"\n', capsys)
    assert "settings.yaml:5: " in err and "notice" in err, err


@pytest.mark.parametrize("kind", BOTH)
@pytest.mark.parametrize("value", ['""', "''", "|\n  ", ">-\n"])
def test_every_way_of_writing_an_empty_notice_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str, value: str
) -> None:
    err = _refuse(tmp_path, kind, KINDS[kind][1] + f"notice: {value}\n", capsys)
    assert "settings.yaml:5: " in err and "notice" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_notice_first_in_the_file_is_reported_at_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    err = _refuse(tmp_path, kind, "notice: 5\n" + KINDS[kind][1], capsys)
    assert "settings.yaml:1: " in err and "notice" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_notice_in_the_middle_is_reported_at_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    text = "# a comment\n\nnotice: ''\n" + KINDS[kind][1]
    err = _refuse(tmp_path, kind, text, capsys)
    assert "settings.yaml:3: " in err and "notice" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_notice_given_twice_is_an_error_naming_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # Section 5 (YAML core): a duplicate key is rejected; the one tessera has one notice.
    err = _refuse(tmp_path, kind, KINDS[kind][1] + 'notice: "a"\nnotice: "b"\n', capsys)
    assert "settings.yaml" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_bad_notice_leaves_an_existing_output_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # "no tessera is written": a good tessera already at the output path is not replaced.
    out = _import(tmp_path, kind, _with(kind, "good notice"))
    before = out.read_bytes()
    source = tmp_path / ("things.csv" if kind == "csv" else "things.db")
    (tmp_path / "bad.yaml").write_text(KINDS[kind][1] + "notice: 5\n", encoding="utf-8")
    rc = main(
        ["import", kind, str(source), "--settings", str(tmp_path / "bad.yaml"), "-o", str(out)]
    )
    capsys.readouterr()
    assert rc == 1
    assert out.read_bytes() == before


def _with(kind: str, notice: str) -> str:
    return f"notice: {_quoted(notice)}\n" + KINDS[kind][1]


# --- the text is kept exactly (sections 3.1, 3.6) -----------------------------------------------

TEXTS = {
    "quotes": "It's \"quoted\" and 'single', with a back\\slash.",
    "astral": "Data \U0001f600 \U00010348 end",
    "combining": "Cafe\u0301 and caf\u00e9",  # not normalised: both forms kept
    "crlf": "line one\r\nline two\rline three\n",
    "surrounding space": "  leading and trailing  ",
    "tab": "a\tb",
    "trailing newline": "one line\n",
    "json-looking": '{"a": [1, 2]}',
    "yaml-looking": "- a: b # not a comment",
    "single char": "x",
    "whitespace only": " ",
    "escaped nul text": "\\u0000",  # six ASCII characters, allowed (section 3.1)
    "long": "MIT License. " * 10_000,
}


@pytest.mark.parametrize("kind", BOTH)
@pytest.mark.parametrize("name", sorted(TEXTS))
def test_the_notice_text_is_stored_byte_for_byte(tmp_path: Path, kind: str, name: str) -> None:
    # Section 3.2 / 10: notices travel unchanged. No strip, no normalisation, no newline change.
    text = TEXTS[name]
    out = _import(tmp_path, kind, _with(kind, text))
    ((got,),) = _rows(out, "SELECT notice FROM source")
    assert isinstance(got, str)
    assert got.encode("utf-8") == text.encode("utf-8")
    ((settings,),) = _rows(out, "SELECT settings FROM header")
    assert json.loads(str(settings))["notice"] == text


@pytest.mark.parametrize("kind", BOTH)
def test_a_notice_as_a_yaml_block_scalar_is_its_text(tmp_path: Path, kind: str) -> None:
    text = KINDS[kind][1] + "notice: |\n  Line one.\n  Line two.\n"
    out = _import(tmp_path, kind, text)
    assert _rows(out, "SELECT notice FROM source") == [("Line one.\nLine two.\n",)]


@pytest.mark.parametrize("kind", BOTH)
def test_a_tessera_with_a_hard_notice_passes_the_checker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # The knowledge hash encodes text as quote() does (section 3.6); the checker recomputes it.
    out = _import(tmp_path, kind, _with(kind, TEXTS["quotes"] + TEXTS["astral"]))
    assert main(["check", str(out)]) == 0, capsys.readouterr()


# --- the settings and the hash (sections 3.3, 3.6, 4.1) ----------------------------------------


@pytest.mark.parametrize("kind", BOTH)
def test_the_same_source_and_notice_give_the_same_bytes_and_hash_twice(
    tmp_path: Path, kind: str
) -> None:
    a = _import(tmp_path / "a", kind, _with(kind, TEXTS["quotes"]))
    b = _import(tmp_path / "b", kind, _with(kind, TEXTS["quotes"]))
    assert _hash(a) == _hash(b)
    assert _rows(a, "SELECT settings FROM header") == _rows(b, "SELECT settings FROM header")


@pytest.mark.parametrize("kind", BOTH)
def test_where_the_notice_stands_in_the_file_does_not_change_the_tessera(
    tmp_path: Path, kind: str
) -> None:
    notice = f"notice: {_quoted('N')}\n"
    first = _import(tmp_path / "a", kind, notice + KINDS[kind][1])
    last = _import(tmp_path / "b", kind, KINDS[kind][1] + notice)
    assert _hash(first) == _hash(last)
    assert _rows(first, "SELECT settings FROM header") == _rows(last, "SELECT settings FROM header")


@pytest.mark.parametrize("kind", BOTH)
def test_two_different_notices_give_two_hashes(tmp_path: Path, kind: str) -> None:
    a = _import(tmp_path / "a", kind, _with(kind, "A"))
    b = _import(tmp_path / "b", kind, _with(kind, "B"))
    assert _hash(a) != _hash(b)


@pytest.mark.parametrize("kind", BOTH)
def test_a_notice_differing_only_in_a_space_or_a_newline_is_a_different_tessera(
    tmp_path: Path, kind: str
) -> None:
    hashes = {
        _hash(_import(tmp_path / str(i), kind, _with(kind, text)))
        for i, text in enumerate(["MIT", "MIT ", "MIT\n", " MIT"])
    }
    assert len(hashes) == 4


@pytest.mark.parametrize("kind", BOTH)
def test_the_notice_changes_only_the_notice_and_the_settings(tmp_path: Path, kind: str) -> None:
    plain = _import(tmp_path / "a", kind, KINDS[kind][1])
    noticed = _import(tmp_path / "b", kind, _with(kind, "N"))
    for table in ("node", "edge", "evidence", "type", "alias"):
        sql = f"SELECT * FROM {table}"
        assert _rows(plain, sql) == _rows(noticed, sql), table
    old = _rows(plain, "SELECT sid, id, kind, hash FROM source")
    assert old == _rows(noticed, "SELECT sid, id, kind, hash FROM source")
    ((s_plain,),) = _rows(plain, "SELECT settings FROM header")
    ((s_noticed,),) = _rows(noticed, "SELECT settings FROM header")
    expected = json.loads(str(s_plain))
    expected["notice"] = "N"
    assert json.loads(str(s_noticed)) == expected


@pytest.mark.parametrize("kind", BOTH)
def test_a_tessera_with_a_notice_has_exactly_one_source_row(tmp_path: Path, kind: str) -> None:
    settings = _with(kind, "N")
    if kind == "sqlite":
        settings += "  Other:\n    label: name\n"
    out = _import(tmp_path, kind, settings)
    assert len(_rows(out, "SELECT 1 FROM source")) == 1


@pytest.mark.parametrize("kind", BOTH)
def test_the_notice_alone_does_not_stand_for_the_other_settings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # A wrong setting elsewhere is still an error with the notice present.
    bad = _with(kind, "N") + "nonsense_setting: 1\n"
    err = _refuse(tmp_path, kind, bad, capsys)
    assert "settings.yaml" in err and "nonsense_setting" in err


@pytest.mark.parametrize("kind", BOTH)
def test_a_tessera_with_a_notice_is_still_a_valid_tessera(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    out = _import(tmp_path, kind, _with(kind, "N"))
    assert main(["check", str(out)]) == 0, capsys.readouterr()


def test_a_csv_with_only_a_header_still_carries_the_notice(tmp_path: Path) -> None:
    source = tmp_path / "empty.csv"
    source.write_text("id,name\n", encoding="utf-8")
    settings = tmp_path / "settings.yaml"
    settings.write_text(_with("csv", "N"), encoding="utf-8")
    out = tmp_path / "e.tessera"
    rc = main(["import", "csv", str(source), "--settings", str(settings), "-o", str(out)])
    assert rc == 0
    assert _rows(out, "SELECT notice FROM source") == [("N",)]


# --- the mosaic carries it (sections 3.2, 7.2, 10) ---------------------------------------------


def _pattern(directory: Path, pieces: dict[str, str]) -> Path:
    listing = "".join(f"  - {name}@{digest}\n" for name, digest in pieces.items())
    froms = "".join(f"      {name}.Thing: {{id: key}}\n" for name in pieces)
    path = directory / "pattern.yaml"
    path.write_text(
        'format: "0.1"\n'
        f"pieces:\n{listing}"
        "types:\n"
        "  Thing:\n"
        "    key: id\n"
        "    describe: An invented thing\n"
        "    from:\n"
        f"{froms}"
        "mosaics:\n  small: {vectors: false}\n",
        encoding="utf-8",
    )
    return path


def _build(directory: Path, pieces: dict[str, Path]) -> tuple[Path, dict[str, object]]:
    pattern = _pattern(directory, {name: _hash(path) for name, path in pieces.items()})
    out = directory / "out"
    args = ["build", str(pattern), "--target", "small", "--pieces", str(directory / "pieces")]
    assert main([*args, "-o", str(out)]) == 0
    report = json.loads((out / "build-report.json").read_text(encoding="utf-8"))
    return out / "small.mosaic", report


def _piece(directory: Path, kind: str, name: str, notice: str | None) -> Path:
    settings = KINDS[kind][1] if notice is None else _with(kind, notice)
    return _import(directory, kind, settings, name)


def test_two_pieces_with_different_notices_give_two_report_entries_sorted_by_piece(
    tmp_path: Path,
) -> None:
    # Section 7.2: one entry per distinct piece name and notice text, sorted by piece then text.
    zed = _piece(tmp_path / "z", "csv", "zed", "Zed notice")
    abe = _piece(tmp_path / "a", "csv", "abe", "Abe notice")
    for p in (zed, abe):
        (tmp_path / "pieces").mkdir(exist_ok=True)
        (tmp_path / "pieces" / p.name).write_bytes(p.read_bytes())
    mosaic, report = _build(tmp_path, {"zed": zed, "abe": abe})
    assert report["notices"] == [
        {"piece": "abe", "text": "Abe notice"},
        {"piece": "zed", "text": "Zed notice"},
    ]
    rows = _rows(mosaic, "SELECT id, notice FROM source ORDER BY id")
    assert ("abe/things.csv", "Abe notice") in rows
    assert ("zed/things.csv", "Zed notice") in rows


def test_the_same_notice_on_two_pieces_is_two_entries_and_two_rows(tmp_path: Path) -> None:
    # Section 3.2: a file that reaches the mosaic through two pieces is two rows, each with the
    # notice that piece published; section 7.2: one entry per distinct piece name and text.
    one = _piece(tmp_path / "a", "csv", "one", "Same")
    two = _import(tmp_path / "b", "csv", _with("csv", "Same").replace("props: [name]", ""), "two")
    (tmp_path / "pieces").mkdir(exist_ok=True)
    for p in (one, two):
        (tmp_path / "pieces" / p.name).write_bytes(p.read_bytes())
    mosaic, report = _build(tmp_path, {"one": one, "two": two})
    assert report["notices"] == [
        {"piece": "one", "text": "Same"},
        {"piece": "two", "text": "Same"},
    ]
    rows = _rows(mosaic, "SELECT id, notice FROM source WHERE notice IS NOT NULL ORDER BY id")
    assert rows == [("one/things.csv", "Same"), ("two/things.csv", "Same")]


def test_a_piece_without_a_notice_adds_no_report_entry_beside_one_with(tmp_path: Path) -> None:
    with_ = _piece(tmp_path / "a", "csv", "noted", "Noted")
    without = _piece(tmp_path / "b", "csv", "plain", None)
    (tmp_path / "pieces").mkdir(exist_ok=True)
    for p in (with_, without):
        (tmp_path / "pieces" / p.name).write_bytes(p.read_bytes())
    mosaic, report = _build(tmp_path, {"noted": with_, "plain": without})
    assert report["notices"] == [{"piece": "noted", "text": "Noted"}]
    assert _rows(mosaic, "SELECT notice FROM source WHERE id = 'plain/things.csv'") == [(None,)]


def test_a_csv_piece_and_a_sqlite_piece_both_carry_their_notices(tmp_path: Path) -> None:
    c = _piece(tmp_path / "a", "csv", "from_csv", "CSV notice")
    s = _piece(tmp_path / "b", "sqlite", "from_db", "DB notice")
    (tmp_path / "pieces").mkdir(exist_ok=True)
    for p in (c, s):
        (tmp_path / "pieces" / p.name).write_bytes(p.read_bytes())
    mosaic, report = _build(tmp_path, {"from_csv": c, "from_db": s})
    assert report["notices"] == [
        {"piece": "from_csv", "text": "CSV notice"},
        {"piece": "from_db", "text": "DB notice"},
    ]
    assert _rows(mosaic, "SELECT id, notice FROM source WHERE notice IS NOT NULL ORDER BY id") == [
        ("from_csv/things.csv", "CSV notice"),
        ("from_db/things.db", "DB notice"),
    ]


@pytest.mark.parametrize("kind", BOTH)
def test_the_mosaic_carries_a_hard_notice_byte_for_byte_and_passes_the_checker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    text = TEXTS["quotes"] + "\n" + TEXTS["astral"] + "\r\n" + TEXTS["combining"]
    piece = _piece(tmp_path, kind, "things", text)
    mosaic, report = _build(tmp_path, {"things": piece})
    assert report["notices"] == [{"piece": "things", "text": text}]
    ((got,),) = _rows(mosaic, "SELECT notice FROM source WHERE notice IS NOT NULL")
    assert str(got).encode("utf-8") == text.encode("utf-8")
    assert main(["check", str(mosaic), "--pieces", str(tmp_path / "pieces")]) == 0, (
        capsys.readouterr()
    )


@pytest.mark.parametrize("kind", BOTH)
def test_two_builds_from_a_noticed_tessera_give_the_same_knowledge_hash(
    tmp_path: Path, kind: str
) -> None:
    piece = _piece(tmp_path, kind, "things", "N")
    m1, r1 = _build(tmp_path, {"things": piece})
    first_hash = _hash(m1)
    (tmp_path / "out2").mkdir()
    pattern = tmp_path / "pattern.yaml"
    out2 = tmp_path / "out2"
    args = ["build", str(pattern), "--target", "small", "--pieces", str(tmp_path / "pieces")]
    assert main([*args, "-o", str(out2)]) == 0
    assert _hash(out2 / "small.mosaic") == first_hash
    assert (out2 / "small.mosaic").read_bytes() == m1.read_bytes()
    assert r1["notices"] == [{"piece": "things", "text": "N"}]


def test_the_noticed_and_the_plain_piece_build_to_different_mosaics(tmp_path: Path) -> None:
    plain = _piece(tmp_path / "a", "csv", "things", None)
    noticed = _piece(tmp_path / "b", "csv", "things", "N")
    hashes = set()
    for i, piece in enumerate((plain, noticed)):
        d = tmp_path / f"build{i}"
        (d / "pieces").mkdir(parents=True)
        (d / "pieces" / piece.name).write_bytes(piece.read_bytes())
        mosaic, _ = _build(d, {"things": piece})
        hashes.add(_hash(mosaic))
    assert len(hashes) == 2


def test_the_error_names_the_setting_not_only_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    err = _refuse(tmp_path, "csv", CSV_SETTINGS + "notice: 5\n", capsys)
    assert re.search(r"settings\.yaml:\d+: .*notice", err), err
