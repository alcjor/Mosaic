"""Regenerate every generated file, or check that they are up to date (gate 5).

uv run scripts/gen.py           # regenerate
uv run scripts/gen.py --check   # fail if regenerating would change anything
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each generator returns {path: content} for the files it owns.
GENERATORS: dict[str, Callable[[], dict[Path, bytes]]] = {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if any generated file is stale")
    ap.add_argument(
        "only", nargs="*", help=f"generators to run (default all): {', '.join(GENERATORS)}"
    )
    args = ap.parse_args()
    stale: list[str] = []
    for name, gen in GENERATORS.items():
        if args.only and name not in args.only:
            continue
        for path, content in gen().items():
            current = path.read_bytes() if path.exists() else None
            if current == content:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if args.check:
                stale.append(f"{name}: {rel}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                print(f"wrote {rel}")
    for s in stale:
        print("stale:", s)
    if stale:
        print("Run `uv run scripts/gen.py` and commit the result.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
