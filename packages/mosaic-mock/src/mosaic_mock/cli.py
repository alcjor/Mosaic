"""``mosaic-mock``: generate an invented system with its ground truth (04-mocker § 4)."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
from pathlib import Path

from mosaic_mock import profiles
from mosaic_mock.engine.generate import generate, write


def _generate(args: argparse.Namespace) -> int:
    profile = profiles.get(args.profile)
    if args.size not in profile.sizes:
        print(f"unknown size {args.size!r}; known: {', '.join(profile.sizes)}", file=sys.stderr)
        return 2
    defects: str | Path = args.defects
    if args.defects not in ("none", "default", "all"):
        defects = Path(args.defects)
    t = time.perf_counter()
    gen = generate(
        profile,
        size=args.size,
        scale=args.scale,
        seed=args.seed,
        defects=defects,
        date=dt.date.fromisoformat(args.date),
        llm=args.llm,
        cache_dir=Path(args.cache_dir),
    )
    write(Path(args.out), gen)
    truth = gen.truth
    print(
        f"{profile.name}/{args.size} seed {args.seed}: {len(gen.files)} files, "
        f"{len(truth['items'])} items, {len(truth['mentions'])} mentions, "
        f"{len(truth['xrefs'])} cross-references, {len(truth['defects'])} defects "
        f"in {time.perf_counter() - t:.1f} s -> {args.out}"
    )
    return 0


def _list_profiles(_: argparse.Namespace) -> int:
    for name in profiles.NAMES:
        p = profiles.get(name)
        print(f"{name}: sizes {', '.join(p.sizes)}")
    return 0


def _list_defects(args: argparse.Namespace) -> int:
    p = profiles.get(args.profile)
    default = set(p.default_defects)
    for kind, inj in p.defect_injectors().items():
        mark = " (default)" if kind in default else ""
        print(f"{inj.code} {kind}{mark}: {inj.where} -> {inj.expected_detection}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mosaic-mock", description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate a mock system")
    g.add_argument("--profile", default="spacecraft", choices=profiles.NAMES)
    g.add_argument("--size", default="small")
    g.add_argument("--scale", type=float, default=1.0, help="multiply the preset's counts")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--defects", default="none", help="none | default | all | <file.yaml>")
    g.add_argument(
        "--llm", default=None, help="rewrite prose with an LLM provider (e.g. anthropic)"
    )
    g.add_argument("--cache-dir", default="mock-cache", help="LLM response cache (MOCK-22)")
    g.add_argument("--date", default="2026-01-01", help="date written into documents")
    g.add_argument("--out", required=True)
    g.set_defaults(func=_generate)

    lp = sub.add_parser("list-profiles", help="list profiles and sizes")
    lp.set_defaults(func=_list_profiles)

    ld = sub.add_parser("list-defects", help="list the defect kinds of a profile")
    ld.add_argument("--profile", default="spacecraft", choices=profiles.NAMES)
    ld.set_defaults(func=_list_defects)

    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s"
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
