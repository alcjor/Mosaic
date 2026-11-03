"""The ``mosaic`` command line.

Subcommands arrive milestone by milestone (docs/design.md, Part 1,
"Milestones"): ``import`` and ``build`` and ``check`` in M1, ``view`` in M2,
``export`` in M3.
"""

from __future__ import annotations

import argparse
import sys

from mosaic_format import FORMAT_VERSION

from mosaic_build import __version__

PLANNED = {
    "check": "M1",
    "import": "M1",
    "build": "M1",
    "view": "M2",
    "export": "M3",
}


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
    for name, milestone in PLANNED.items():
        sub.add_parser(name, help=f"not implemented yet (planned for {milestone})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(
        f"mosaic {args.command}: not implemented yet (planned for {PLANNED[args.command]})",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
