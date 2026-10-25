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



def examples() -> dict[Path, bytes]:
    """examples/demosat-1: the small clean mission, seed 42 (MOCK-17)."""
    from mosaic_mock import profiles
    from mosaic_mock.engine import truth
    from mosaic_mock.engine.generate import generate

    out = ROOT / "examples" / "demosat-1"
    gen = generate(profiles.get("spacecraft"), size="small", seed=42)
    files = {out / rel: data for rel, data in gen.files.items()}
    files[out / "ground_truth.json"] = truth.dumps(gen.truth)
    return files


# Each generator returns {path: content} for the files it owns.
GENERATORS: dict[str, Callable[[], dict[Path, bytes]]] = {
    "examples": examples,
}
# Folders wholly owned by a generator: any other file there is stale (build/ is ignored).
OWNED = {"examples": ROOT / "examples" / "demosat-1"}


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
        produced = gen()
        owned = OWNED.get(name)
        if owned and owned.exists():
            for f in owned.rglob("*"):
                if f.is_file() and "build" not in f.relative_to(owned).parts and f not in produced:
                    if args.check:
                        stale.append(f"{name}: {f.relative_to(ROOT).as_posix()} (not generated)")
                    else:
                        f.unlink()
                        print(f"removed {f.relative_to(ROOT).as_posix()}")
        for path, content in produced.items():
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
