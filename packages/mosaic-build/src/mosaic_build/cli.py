"""The ``mosaic`` command line.

Subcommands arrive milestone by milestone (docs/design.md, Part 1, "Milestones"): ``import``,
``build`` and ``check`` in M1, ``view`` in M2, ``export`` in M3.

- ``mosaic import csv <file> --settings <file> -o <out.tessera>`` writes one tessera from one
  CSV file (:mod:`mosaic_build.tessera.csv`). The settings file has the shape of the tessera's
  ``header.settings`` (:mod:`mosaic_build.tessera.settings`). Values a conversion could not
  read are listed on standard error.
- ``mosaic build <pattern.yaml> [--target T] [--pieces DIR] [--model DIR] [-o DIR]`` builds one
  target into ``DIR/<target>.mosaic``, with ``build-report.json`` beside it (Specification 0.1,
  section 7.2); ``DIR`` is the current directory unless given. Without ``--target`` the pattern must
  have one target, such as the ``default`` of a pattern without ``mosaics`` (section 5.4). The
  available pieces (section 5.1) are the SQLite files directly in ``--pieces DIR`` and the files
  the pieces' own ``path`` names; ``proposals.yaml`` beside the pattern is the build's proposals
  file (section 5). The report's path is printed, also when the build fails. The report in
  ``DIR`` is that of the last build there; build each target into its own ``DIR`` to keep both.
  A target with vectors on (the default) needs ``--model DIR``, the directory holding the model
  files of section 6 (``scripts/fetch_model.py`` fills it); each file is checked by its
  SHA-256, and without them the build fails with ``invalid_input``. The command never fetches
  them: the builder uses no network (section 7).
- ``mosaic check <file> [--pieces DIR]`` checks a tessera or mosaic (an SQLite file) by section
  3.9, or else a pattern, with ``proposals.yaml`` beside it, by sections 5 and 5.6. It prints
  one line per violation, or ``<file>: ok``, and lists on standard error the rules it could not
  run. Without ``--pieces``, a pattern's piece rules are not run.

Exit status: 0 when the command did what was asked, 1 when a build failed, a check found
violations or an input could not be read, 2 for a command line that is not understood.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from mosaic_format import FORMAT_VERSION
from mosaic_format.check import check_file
from mosaic_format.file import SIDECARS
from mosaic_format.pattern import check_pattern
from mosaic_format.yaml_core import YamlError, load

from mosaic_build import __version__
from mosaic_build.mosaic import BuildError, build
from mosaic_build.mosaic.pieces import piece_paths
from mosaic_build.mosaic.target import DEFAULT_TARGET
from mosaic_build.tessera import csv as csv_tessera
from mosaic_build.tessera import settings as csv_settings

PLANNED = {
    "view": "M2",
    "export": "M3",
}
"""Commands of later milestones, which say so and exit with status 2."""

SQLITE_MAGIC = b"SQLite format 3\x00"
"""The first 16 bytes of every SQLite 3 database file, so of every tessera and mosaic."""

TARGET_NAME = re.compile(r"[a-z][a-z0-9_-]*")
"""Target names (``pattern.schema.json``); a target's mosaic is ``<target>.mosaic``."""

PROPOSALS = "proposals.yaml"
"""The proposals file beside a pattern (section 5)."""


class _Usage(Exception):
    """A command line that cannot be run as given: exit status 2."""


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mosaic",
        description="Build and check Mosaic tesserae and mosaics.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mosaic {__version__} (format {FORMAT_VERSION})",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    importer = sub.add_parser("import", help="write a tessera from one source")
    kinds = importer.add_subparsers(dest="kind", metavar="KIND", required=True)
    csv_cmd = kinds.add_parser("csv", help="one CSV file, one row per node")
    csv_cmd.add_argument("file", type=Path, help="the CSV file (only read)")
    csv_cmd.add_argument(
        "--settings",
        type=Path,
        required=True,
        help="YAML file in the shape of the tessera's header.settings",
    )
    csv_cmd.add_argument(
        "-o", "--output", type=Path, required=True, help="the new tessera file to write"
    )

    builder = sub.add_parser("build", help="build a mosaic from pieces and a pattern")
    builder.add_argument("pattern", type=Path, help="the pattern file, pattern.yaml")
    builder.add_argument(
        "--target", help="the target to build; needed when the pattern has several"
    )
    builder.add_argument("--pieces", type=Path, help="directory of available piece files")
    builder.add_argument(
        "--model",
        type=Path,
        help="directory of the embedding model files (section 6); needed for vectors",
    )
    builder.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(),
        help="directory for <target>.mosaic and build-report.json (default: current)",
    )

    checker = sub.add_parser("check", help="check a tessera, a mosaic or a pattern")
    checker.add_argument("file", type=Path, help="a tessera, a mosaic or pattern.yaml")
    checker.add_argument("--pieces", type=Path, help="directory of available piece files")

    for name, milestone in PLANNED.items():
        sub.add_parser(name, help=f"not implemented yet (planned for {milestone})")
    return parser


def _error(command: str, message: object) -> None:
    print(f"mosaic {command}: {message}", file=sys.stderr)


def _is_sqlite(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def _candidates(directory: Path | None) -> list[Path]:
    """The SQLite files directly in ``directory``: the available pieces it offers."""
    if directory is None:
        return []
    if not directory.is_dir():
        raise _Usage(f"--pieces {directory}: no such directory")
    files = [p for p in directory.iterdir() if p.is_file() and _is_sqlite(p)]
    return sorted(files, key=lambda p: os.fsencode(p.name))


def _proposals(pattern: Path) -> Path | None:
    path = pattern.parent / PROPOSALS
    return path if path.is_file() and path.name != pattern.name else None


def _pattern_data(pattern: Path) -> object:
    """The pattern's data, or None when it cannot be read (the check then says why)."""
    try:
        return load(pattern.read_bytes().decode("utf-8"), str(pattern)).data
    except OSError, UnicodeDecodeError, YamlError:
        return None


def _only_target(pattern: Path) -> str:
    """The pattern's one target; several are a usage error (section 5.4)."""
    data = _pattern_data(pattern)
    mosaics = data.get("mosaics") if isinstance(data, dict) else None
    if not isinstance(mosaics, dict) or not mosaics:
        return DEFAULT_TARGET  # no targets is `default`; a bad pattern fails the build
    names = list(mosaics)
    if len(names) == 1:
        return str(names[0])
    listed = ", ".join(repr(n) for n in names)
    raise _Usage(f"{pattern}: the pattern has several targets ({listed}); choose one with --target")


def _import_csv(args: argparse.Namespace) -> int:
    source: Path = args.file
    out: Path = args.output.absolute()
    try:
        settings = csv_settings.read(args.settings)
    except (OSError, ValueError) as e:
        _error("import csv", e)
        return 1
    if out.exists():
        _error("import csv", f"{out}: exists; a tessera is never overwritten")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        built = csv_tessera.build(source, out, settings)
    except (OSError, ValueError) as e:
        _error("import csv", e)
        return 1
    print(f"tessera {built.path}")
    print(f"knowledge_hash {built.knowledge_hash}")
    for column, rows in built.report.unconverted.items():
        if rows:
            n = len(rows)
            listed = ", ".join(str(r) for r in rows)
            kept = f"{n} value{'s' if n != 1 else ''} kept as text"
            where = f"row{'s' if n != 1 else ''} {listed}"
            _error("import csv", f"{source.name}: column {column!r}: {kept} ({where})")
    return 0


def _build(args: argparse.Namespace) -> int:
    pattern: Path = args.pattern
    target = args.target if args.target is not None else _only_target(pattern)
    if TARGET_NAME.fullmatch(target) is None:
        raise _Usage(f"--target {target!r} is not a target name ^[a-z][a-z0-9_-]*$ (5.4)")
    out_dir: Path = args.output.absolute()
    out = out_dir / f"{target}.mosaic"
    for existing in [out, *(out.with_name(out.name + s) for s in SIDECARS)]:
        if existing.exists():
            _error("build", f"{existing}: exists; a mosaic is never overwritten")
            return 1
    pieces = _candidates(args.pieces)
    try:
        built = build(
            pattern,
            target,
            out,
            pieces=tuple(pieces),
            proposals=_proposals(pattern),
            model=args.model,
        )
    except BuildError as e:
        _error("build", f"failed: {e}")
        if e.report is not None:
            print(f"report {e.report}")
        return 1
    for message in built.messages:
        _error("build", message)
    print(f"mosaic {built.path}")
    print(f"knowledge_hash {built.knowledge_hash}")
    print(f"report {built.report}")
    return 0


def _check(args: argparse.Namespace) -> int:
    path: Path = args.file
    if not path.is_file():
        _error("check", f"{path}: no such file")
        return 1
    pieces = _candidates(args.pieces)
    if _is_sqlite(path):
        file_report = check_file(path, pieces=pieces)
        lines = [str(v) for v in file_report.violations]
        skipped = list(file_report.skipped)
    else:
        proposals = _proposals(path)
        report = check_pattern(path, proposals=proposals)
        if report.ok and args.pieces is not None:
            data = _pattern_data(path)
            assert isinstance(data, dict)  # it passed its schema
            available = [*pieces, *piece_paths(path, data)]
            report = check_pattern(path, proposals=proposals, pieces=available)
        lines = [str(v) for v in report.violations]
        skipped = list(report.skipped)
    for line in lines:
        print(line)
    for item in skipped:
        print(f"{path}: not checked: {item}", file=sys.stderr)
    if lines:
        return 1
    print(f"{path}: ok")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command in PLANNED:
        _error(args.command, f"not implemented yet (planned for {PLANNED[args.command]})")
        return 2
    run = {"import": _import_csv, "build": _build, "check": _check}[args.command]
    try:
        return run(args)
    except _Usage as e:
        _error(args.command, e)
        return 2
    except OSError as e:  # an input that cannot be read; the message names the file
        _error(args.command, e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
