"""The ``mosaic`` command line: ``import csv``, ``build`` and ``check`` (issue #18).

The end-to-end test runs the installed entry point in a subprocess, as a user would; the
others call :func:`mosaic_build.cli.main` in-process. Builds follow Specification 0.1,
section 7 (report beside the mosaic, section 7.2; the targets of section 5.4) and checks
sections 3.9, 5 and 5.6.
"""

import importlib
import json
import re
import shutil
import subprocess
import sysconfig
import typing
from pathlib import Path
from typing import Any

import pytest
from mosaic_build.cli import main
from mosaic_build.mosaic.vectors import EMBED_MODEL
from mosaic_format.reader import open as open_sealed

from tests.mosaic.pieces import StubModel

REPO = Path(__file__).resolve().parent.parent
INVALID_FILES = REPO / "conformance" / "invalid" / "files"

CSV = """code,name,family,born,strings
V1,Viola,strings,"March 4, 1535",4
H2,Horn,brass,1650,
O3,Oboe,woodwind,"June 1, 1660",
"""
"""An invented table of instruments; ``born`` has a year that the date formats cannot read."""

SETTINGS = """\
type: Instrument
key: code
label: name
summary: null
props: [family, born, strings]
convert:
  born: {kind: date, formats: ["%B %d, %Y"]}
  strings: {kind: integer}
"""

HASH = re.compile(r"\b[0-9a-f]{64}\b")


def entry_point() -> Path:
    """The installed ``mosaic`` script of the environment running the tests."""
    name = "mosaic.exe" if sysconfig.get_platform().startswith("win") else "mosaic"
    path = Path(sysconfig.get_path("scripts")) / name
    assert path.is_file(), f"{path}: the mosaic entry point is not installed"
    return path


def run(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(entry_point()), *(str(a) for a in args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def write_pattern(directory: Path, piece_hash: str, mosaics: str = "") -> Path:
    path = directory / "pattern.yaml"
    path.write_text(
        f"""\
format: "0.1"
pieces:
  - instruments@{piece_hash[:12]}
types:
  Instrument:
    key: code
    describe: An instrument of the invented table
    from:
      instruments.Instrument: {{code: key, family: family, born: born}}
{mosaics}""",
        encoding="utf-8",
    )
    return path


def imported(tmp_path: Path) -> tuple[Path, str]:
    """Import the invented CSV in-process into ``pieces/instruments.tessera``; its hash."""
    (tmp_path / "instruments.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    out = tmp_path / "pieces" / "instruments.tessera"
    out.parent.mkdir()
    args = ["import", "csv", str(tmp_path / "instruments.csv")]
    assert main([*args, "--settings", str(tmp_path / "settings.yaml"), "-o", str(out)]) == 0
    with open_sealed(out) as sealed:
        return out, sealed.knowledge_hash


# --- end to end, on the installed entry point -------------------------------------------------


def test_import_build_check_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "instruments.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    (tmp_path / "pieces").mkdir()

    # mosaic import csv <file> --settings <yaml> -o <out.tessera>
    tessera = tmp_path / "pieces" / "instruments.tessera"
    done = run(
        "import", "csv", "instruments.csv", "--settings", "settings.yaml", "-o", tessera,
        cwd=tmp_path,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    with open_sealed(tessera) as sealed:
        assert sealed.kind == "tessera"
        piece_hash = sealed.knowledge_hash
        assert sealed.query("SELECT count(*) FROM node") == [(3,)]
    assert piece_hash in done.stdout
    # The builder's report: one value of `born` could not be read and stays text.
    assert "born" in done.stderr and "row 2" in done.stderr

    # mosaic check <tessera>
    done = run("check", tessera, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr

    # mosaic build <pattern.yaml> --target T --pieces DIR -o DIR
    pattern = write_pattern(tmp_path, piece_hash, "mosaics:\n  catalogue: {vectors: false}\n")
    done = run("build", pattern, "--target", "catalogue", "--pieces", "pieces", "-o", "out",
               cwd=tmp_path)  # fmt: skip
    assert done.returncode == 0, done.stderr
    mosaic = tmp_path / "out" / "catalogue.mosaic"
    report = tmp_path / "out" / "build-report.json"
    assert str(report) in done.stdout
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["outcome"] == "built"
    assert data["target"] == "catalogue"
    with open_sealed(mosaic) as sealed:
        assert sealed.kind == "mosaic"
        assert sealed.knowledge_hash == data["knowledge_hash"]
        assert sealed.query("SELECT count(*) FROM node") == [(3,)]
    assert data["knowledge_hash"] in done.stdout

    # mosaic check <mosaic> --pieces DIR, and mosaic check <pattern.yaml> --pieces DIR
    done = run("check", mosaic, "--pieces", "pieces", cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    done = run("check", pattern, "--pieces", "pieces", cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr


def test_end_to_end_failure_exits_non_zero_and_prints_the_report(tmp_path: Path) -> None:
    _, piece_hash = imported(tmp_path)
    mosaics = "mosaics:\n  tiny: {budget: 1 KB, vectors: false}\n"
    pattern = write_pattern(tmp_path, piece_hash, mosaics)
    done = run("build", pattern, "--pieces", "pieces", "-o", "out", cwd=tmp_path)
    assert done.returncode != 0
    report = tmp_path / "out" / "build-report.json"
    assert str(report) in done.stdout
    assert json.loads(report.read_text(encoding="utf-8"))["reason"] == "over_budget"
    assert "over_budget" in done.stderr
    assert not (tmp_path / "out" / "tiny.mosaic").exists()


def test_end_to_end_check_prints_one_line_per_violation(tmp_path: Path) -> None:
    done = run("check", INVALID_FILES / "container.tessera", cwd=tmp_path)
    assert done.returncode == 1
    lines = done.stdout.splitlines()
    assert lines and all("container.tessera" in line for line in lines)


# --- mosaic import csv ------------------------------------------------------------------------


def test_import_records_the_settings_file_as_header_settings(tmp_path: Path) -> None:
    out, _ = imported(tmp_path)
    with open_sealed(out) as sealed:
        ((settings,),) = sealed.query("SELECT settings FROM header")
    assert json.loads(str(settings)) == {
        "type": "Instrument",
        "key": "code",
        "label": "name",
        "summary": None,
        "props": ["family", "born", "strings"],
        "encoding": "utf-8",
        "delimiter": ",",
        "convert": {
            "born": {"kind": "date", "formats": ["%B %d, %Y"]},
            "strings": {"kind": "integer"},
        },
    }


def test_import_header_settings_as_a_settings_file_gives_the_same_tessera(tmp_path: Path) -> None:
    """A tessera's own ``header.settings`` (JSON is YAML) rebuilds it: same knowledge hash."""
    out, piece_hash = imported(tmp_path)
    with open_sealed(out) as sealed:
        ((settings,),) = sealed.query("SELECT settings FROM header")
    again = tmp_path / "settings.json"
    again.write_text(str(settings), encoding="utf-8")
    copy = tmp_path / "copy.tessera"
    args = ["import", "csv", str(tmp_path / "instruments.csv"), "--settings", str(again)]
    assert main([*args, "-o", str(copy)]) == 0
    with open_sealed(copy) as sealed:
        assert sealed.knowledge_hash == piece_hash


def test_import_defaults_for_omitted_settings(tmp_path: Path) -> None:
    (tmp_path / "rows.csv").write_text("a;b\n1;2\n", encoding="utf-8")
    (tmp_path / "s.yaml").write_text("delimiter: ';'\nprops: [b]\n", encoding="utf-8")
    out = tmp_path / "rows.tessera"
    args = ["import", "csv", str(tmp_path / "rows.csv"), "--settings", str(tmp_path / "s.yaml")]
    assert main([*args, "-o", str(out)]) == 0
    with open_sealed(out) as sealed:
        assert sealed.query("SELECT id, props FROM node") == [("Row:1", '{"b":"2"}')]


def test_import_turns_a_column_into_linked_things(tmp_path: Path) -> None:
    """Linked columns from the settings file (plan M1.1): nodes, edges, header.settings."""
    (tmp_path / "rows.csv").write_text('code,tags\nA,"x; y"\nB,y\n', encoding="utf-8")
    (tmp_path / "s.yaml").write_text(
        "type: Item\nkey: code\nlinks:\n  tags: {type: Tag, edge: tagged, separator: ';'}\n",
        encoding="utf-8",
    )
    out = tmp_path / "rows.tessera"
    args = ["import", "csv", str(tmp_path / "rows.csv"), "--settings", str(tmp_path / "s.yaml")]
    assert main([*args, "-o", str(out)]) == 0
    with open_sealed(out) as sealed:
        assert sealed.query("SELECT src, dst FROM v_edge ORDER BY src, dst") == [
            ("Item:A", "Tag:x"),
            ("Item:A", "Tag:y"),
            ("Item:B", "Tag:y"),
        ]
        ((settings,),) = sealed.query("SELECT settings FROM header")
    assert json.loads(str(settings))["links"] == {
        "tags": {"type": "Tag", "edge": "tagged", "direction": "out", "separator": ";"}
    }
    assert main(["check", str(out)]) == 0


@pytest.mark.parametrize(
    ("settings", "named"),
    [
        ("colour: red\n", "colour"),
        ("props: family\n", "props"),
        ("props: [1]\n", "props"),
        ("key: 5\n", "key"),
        ("type: [Row]\n", "type"),
        ("convert: {born: {kind: guess}}\nprops: [born]\n", "guess"),
        ("convert: {born: {kind: date}}\nprops: [born]\n", "formats"),
        ("convert: {born: {kind: integer, base: 8}}\nprops: [born]\n", "base"),
        ("- type\n", "mapping"),
        ("type: A\ntype: B\n", "type"),
        ("links: {born: {type: Year}}\n", "edge"),
        ("links: {born: {type: Year, edge: in_year, direction: sideways}}\n", "direction"),
        ("links: {born: {type: Row, edge: in_year}}\n", "Row"),
    ],
)
def test_import_refuses_bad_settings_naming_the_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], settings: str, named: str
) -> None:
    (tmp_path / "rows.csv").write_text("born\n1\n", encoding="utf-8")
    (tmp_path / "s.yaml").write_text(settings, encoding="utf-8")
    out = tmp_path / "rows.tessera"
    args = ["import", "csv", str(tmp_path / "rows.csv"), "--settings", str(tmp_path / "s.yaml")]
    assert main([*args, "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert "s.yaml" in err and named in err
    assert not out.exists()


def test_import_refuses_an_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, _ = imported(tmp_path)
    before = out.read_bytes()
    args = ["import", "csv", str(tmp_path / "instruments.csv")]
    assert main([*args, "--settings", str(tmp_path / "settings.yaml"), "-o", str(out)]) == 1
    assert str(out) in capsys.readouterr().err
    assert out.read_bytes() == before


def test_import_names_the_file_and_row_of_a_bad_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "rows.csv").write_text("k\nA\nA\n", encoding="utf-8")
    (tmp_path / "s.yaml").write_text("key: k\n", encoding="utf-8")
    out = tmp_path / "rows.tessera"
    args = ["import", "csv", str(tmp_path / "rows.csv"), "--settings", str(tmp_path / "s.yaml")]
    assert main([*args, "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert "rows.csv" in err and "rows 1 and 2" in err
    assert not out.exists()


# --- mosaic build -----------------------------------------------------------------------------


def test_build_without_target_builds_the_only_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pattern without ``mosaics`` has the one target ``default`` (section 5.4)."""
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash)
    out = tmp_path / "out"
    model = _stub_model(tmp_path, monkeypatch)
    args = ["build", str(pattern), "--pieces", str(tmp_path / "pieces"), "--model", str(model)]
    assert main([*args, "-o", str(out)]) == 0
    with open_sealed(out / "default.mosaic") as sealed:
        assert sealed.query("SELECT target FROM header") == [("default",)]
    assert json.loads((out / "build-report.json").read_text("utf-8"))["outcome"] == "built"


def test_build_without_target_refuses_a_pattern_with_several(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, piece_hash = imported(tmp_path)
    mosaics = "mosaics:\n  small: {vectors: false}\n  large: {vectors: false}\n"
    pattern = write_pattern(tmp_path, piece_hash, mosaics)
    out = tmp_path / "out"
    assert main(["build", str(pattern), "--pieces", str(tmp_path / "pieces"), "-o", str(out)]) == 2
    err = capsys.readouterr().err
    assert "--target" in err and "'small'" in err and "'large'" in err
    assert not out.exists()


def test_build_output_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash, "mosaics:\n  one: {vectors: false}\n")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    assert main(["build", str(pattern), "--pieces", str(tmp_path / "pieces")]) == 0
    assert (work / "one.mosaic").is_file()
    assert (work / "build-report.json").is_file()
    assert "build-report.json" in capsys.readouterr().out


def test_build_finds_a_piece_by_its_path_without_pieces_dir(tmp_path: Path) -> None:
    """Each piece's own ``path``, relative to the pattern, is available (section 5.1)."""
    _, piece_hash = imported(tmp_path)
    pattern = tmp_path / "pattern.yaml"
    pattern.write_text(
        f"""\
format: "0.1"
pieces:
  - {{name: instruments, hash: {piece_hash}, path: pieces/instruments.tessera}}
types:
  Instrument:
    key: code
    from:
      instruments.Instrument: {{code: key}}
mosaics:
  plain: {{vectors: false}}
""",
        encoding="utf-8",
    )
    assert main(["build", str(pattern), "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "plain.mosaic").is_file()


def test_build_pieces_dir_skips_files_that_are_not_sqlite(tmp_path: Path) -> None:
    """Notes beside the pieces are no candidate pieces; sealed files are."""
    _, piece_hash = imported(tmp_path)
    (tmp_path / "pieces" / "README.txt").write_text("notes\n", encoding="utf-8")
    pattern = write_pattern(tmp_path, piece_hash, "mosaics:\n  one: {vectors: false}\n")
    out = tmp_path / "out"
    assert main(["build", str(pattern), "--pieces", str(tmp_path / "pieces"), "-o", str(out)]) == 0


def test_build_unknown_target_fails_with_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash, "mosaics:\n  one: {vectors: false}\n")
    out = tmp_path / "out"
    args = ["build", str(pattern), "--target", "two", "--pieces", str(tmp_path / "pieces")]
    assert main([*args, "-o", str(out)]) == 1
    captured = capsys.readouterr()
    assert str(out / "build-report.json") in captured.out
    assert "invalid_input" in captured.err and "'two'" in captured.err
    data = json.loads((out / "build-report.json").read_text("utf-8"))
    assert (data["outcome"], data["reason"]) == ("failed", "invalid_input")


def test_build_missing_piece_fails_with_piece_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pattern = write_pattern(tmp_path, "0123456789ab" * 5 + "0123")
    out = tmp_path / "out"
    assert main(["build", str(pattern), "-o", str(out)]) == 1
    assert "piece_mismatch" in capsys.readouterr().err
    data = json.loads((out / "build-report.json").read_text("utf-8"))
    assert data["reason"] == "piece_mismatch"


def test_build_uses_proposals_beside_the_pattern(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``proposals.yaml`` beside the pattern is the build's proposals file (section 5)."""
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash, "mosaics:\n  one: {vectors: false}\n")
    (tmp_path / "proposals.yaml").write_text("format: '0.1'\nproposals: oops\n", "utf-8")
    out = tmp_path / "out"
    assert main(["build", str(pattern), "--pieces", str(tmp_path / "pieces"), "-o", str(out)]) == 1
    captured = capsys.readouterr()
    assert "invalid_input" in captured.err and "proposals.yaml" in captured.err


def test_build_refuses_to_overwrite_a_mosaic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash, "mosaics:\n  one: {vectors: false}\n")
    out = tmp_path / "out"
    args = ["build", str(pattern), "--pieces", str(tmp_path / "pieces"), "-o", str(out)]
    assert main(args) == 0
    before = (out / "one.mosaic").read_bytes()
    capsys.readouterr()
    assert main(args) == 1
    assert str(out / "one.mosaic") in capsys.readouterr().err
    assert (out / "one.mosaic").read_bytes() == before


# --- mosaic build --model (section 6) ---------------------------------------------------------


class _StubEmbedder(StubModel):
    """Stands in for :class:`mosaic_build.mosaic.vectors.Embedder`; records its directory."""

    directories: typing.ClassVar[list[Path]] = []

    def __init__(self, model_dir: Path) -> None:
        super().__init__()
        self.directories.append(model_dir)


def _stub_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A model directory, and the builder's model replaced by a stub that records it."""
    model = tmp_path / "model"
    model.mkdir()
    _StubEmbedder.directories.clear()
    # The package exports the function `build`, so the module is taken by its import name.
    module = importlib.import_module("mosaic_build.mosaic.build")
    monkeypatch.setattr(module, "Embedder", _StubEmbedder)
    return model


def test_build_with_model_builds_vectors_from_that_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash)  # default target: vectors on
    out = tmp_path / "out"
    model = _stub_model(tmp_path, monkeypatch)
    args = ["build", str(pattern), "--pieces", str(tmp_path / "pieces"), "--model", str(model)]
    assert main([*args, "-o", str(out)]) == 0
    assert _StubEmbedder.directories == [model]
    with open_sealed(out / "default.mosaic") as sealed:
        ((vector_hash, embed_model),) = sealed.query("SELECT vector_hash, embed_model FROM header")
        ((vectors, nodes),) = sealed.query(
            "SELECT (SELECT count(*) FROM vector), (SELECT count(*) FROM node)"
        )
    assert embed_model == EMBED_MODEL
    assert isinstance(nodes, int)
    assert vectors == nodes > 0
    report = json.loads((out / "build-report.json").read_text("utf-8"))
    assert report["vector_hash"] == vector_hash is not None
    assert "skipped" not in capsys.readouterr().err


def test_build_with_vectors_on_and_no_model_fails_with_invalid_input(tmp_path: Path) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash)  # default target: vectors on
    done = run("build", pattern, "--pieces", "pieces", "-o", "out", cwd=tmp_path)
    assert done.returncode == 1
    assert "vectors" in done.stderr and "model" in done.stderr
    assert "invalid_input" in done.stderr
    report = tmp_path / "out" / "build-report.json"
    assert str(report) in done.stdout
    assert json.loads(report.read_text(encoding="utf-8"))["reason"] == "invalid_input"
    assert not (tmp_path / "out" / "default.mosaic").exists()


def test_build_with_a_model_directory_missing_its_files_fails_naming_the_file(
    tmp_path: Path,
) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash)
    (tmp_path / "model").mkdir()
    done = run(
        "build", pattern, "--pieces", "pieces", "--model", "model", "-o", "out", cwd=tmp_path
    )
    assert done.returncode == 1
    assert "onnx/model_quantized.onnx" in done.stderr
    assert json.loads((tmp_path / "out" / "build-report.json").read_text("utf-8"))["reason"] == (
        "invalid_input"
    )
    assert not (tmp_path / "out" / "default.mosaic").exists()


def test_build_with_vectors_off_needs_no_model(tmp_path: Path) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash, "mosaics:\n  plain: {vectors: false}\n")
    done = run("build", pattern, "--pieces", "pieces", "-o", "out", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    with open_sealed(tmp_path / "out" / "plain.mosaic") as sealed:
        assert sealed.query("SELECT vector_hash, embed_model FROM header") == [(None, None)]
    assert "skipped" not in done.stderr


def test_build_help_documents_model() -> None:
    done = subprocess.run(
        [str(entry_point()), "build", "--help"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0
    assert "--model" in done.stdout and "section 6" in done.stdout


# --- mosaic check -----------------------------------------------------------------------------


def test_check_a_valid_pattern_without_pieces_says_which_rules_it_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, piece_hash = imported(tmp_path)
    capsys.readouterr()
    pattern = write_pattern(tmp_path, piece_hash)
    assert main(["check", str(pattern)]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"{pattern}: ok"
    assert "piece-unmatched" in captured.err


def test_check_a_pattern_with_pieces_reports_unmatched_pieces(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    imported(tmp_path)
    capsys.readouterr()
    pattern = write_pattern(tmp_path, "ab" * 32)
    assert main(["check", str(pattern), "--pieces", str(tmp_path / "pieces")]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and "piece-unmatched" in lines[0]


def test_check_a_pattern_checks_proposals_beside_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, piece_hash = imported(tmp_path)
    pattern = write_pattern(tmp_path, piece_hash)
    (tmp_path / "proposals.yaml").write_text("format: '0.1'\nproposals: oops\n", "utf-8")
    assert main(["check", str(pattern)]) == 1
    out = capsys.readouterr().out
    assert "proposals.yaml" in out and "[schema" in out


def test_check_invalid_pattern_one_line_per_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pattern = tmp_path / "pattern.yaml"
    pattern.write_text("format: '0.1'\npieces: []\ntypes: {}\nextra: 1\n", "utf-8")
    assert main(["check", str(pattern)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) >= 3
    assert all(line.startswith(str(pattern)) for line in lines)


def test_check_every_invalid_file_fails_on_its_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each case of ``conformance/invalid/files``, with its pieces in a ``--pieces`` directory."""
    cases = json.loads((INVALID_FILES / "cases.json").read_text(encoding="utf-8"))
    assert cases
    rule = re.compile(r"\[(invariant (\d+)|[a-z0-9-]+), section [0-9.]+\]$")
    for name, case in cases.items():
        path = INVALID_FILES / name
        args = ["check", str(path)]
        if case["pieces"]:
            pieces = tmp_path / name
            pieces.mkdir()
            for piece in case["pieces"]:
                shutil.copyfile(INVALID_FILES / piece, pieces / piece)
            args += ["--pieces", str(pieces)]
        assert main(args) == 1, name
        lines = capsys.readouterr().out.splitlines()
        assert lines and all(line.startswith(str(path)) for line in lines), name
        found = set()
        for line in lines:
            m = rule.search(line)
            assert m is not None, line
            found.add(f"inv-{m[2]}" if m[2] else m[1])
        assert found == set(case["rules"]), name


def test_check_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(tmp_path / "nothing.tessera")]) == 1
    assert "nothing.tessera" in capsys.readouterr().err


def test_an_unreadable_input_is_named_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file that cannot be opened exits 1 with a message naming it."""
    locked = tmp_path / "locked.tessera"
    locked.write_bytes(b"SQLite format 3\x00")
    real_open = Path.open

    def refuse(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if self.name == "locked.tessera":
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    assert main(["check", str(locked)]) == 1
    assert str(locked) in capsys.readouterr().err
    pattern = write_pattern(tmp_path, "ab" * 32)
    assert main(["check", str(pattern), "--pieces", str(tmp_path)]) == 1
    assert str(locked) in capsys.readouterr().err
    assert main(["build", str(pattern), "--pieces", str(tmp_path), "-o", str(tmp_path / "o")]) == 1
    assert str(locked) in capsys.readouterr().err


# --- the command itself -----------------------------------------------------------------------


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "format 0.1" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["view", "export"])
def test_later_commands_fail_loudly(command: str) -> None:
    assert main([command]) == 2


def test_hashes_printed_are_full_hashes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "rows.csv").write_text("a\n1\n", encoding="utf-8")
    (tmp_path / "s.yaml").write_text("props: [a]\n", encoding="utf-8")
    out = tmp_path / "rows.tessera"
    args = ["import", "csv", str(tmp_path / "rows.csv"), "--settings", str(tmp_path / "s.yaml")]
    assert main([*args, "-o", str(out)]) == 0
    with open_sealed(out) as sealed:
        assert HASH.findall(capsys.readouterr().out) == [sealed.knowledge_hash]
