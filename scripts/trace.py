"""Traceability (engineering.md § 5): list requirement IDs in the specs that no test covers.

Python tests declare coverage with ``@pytest.mark.req("CORE-41")``; viewer tests (Vitest
and Playwright) name the ID in the test title, e.g. ``test("VIEW-10 clicking a mention")``.
Fails on gaps unless ``--warn`` is given.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ_DEF = re.compile(r"\*\*([A-Z]+-\d+)\*\*")
PY_REQ = re.compile(r"""req\(([^)]*)\)""")
ID = re.compile(r"\b(?:CORE|PACK|VIEW|MOCK)-\d+\b")


def spec_ids() -> dict[str, str]:
    ids: dict[str, str] = {}
    for f in sorted((ROOT / "docs" / "specs").glob("*.md")):
        for m in REQ_DEF.finditer(f.read_text(encoding="utf-8")):
            ids.setdefault(m.group(1), f.name)
    return ids


def covered_ids() -> set[str]:
    found: set[str] = set()
    py_files = [*ROOT.glob("packages/*/tests/**/*.py"), *ROOT.glob("tests/**/*.py")]
    for f in py_files:
        for m in PY_REQ.finditer(f.read_text(encoding="utf-8")):
            found.update(ID.findall(m.group(1)))
    ts_files = [p for p in ROOT.glob("viewer/**/*.ts") if "node_modules" not in p.parts]
    for f in ts_files:
        if f.name.endswith((".test.ts", ".spec.ts")):
            found.update(ID.findall(f.read_text(encoding="utf-8")))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--warn", action="store_true", help="report gaps without failing")
    args = ap.parse_args()
    ids = spec_ids()
    covered = covered_ids()
    missing = [i for i in ids if i not in covered]
    unknown = sorted(covered - set(ids))
    print(f"{len(ids) - len(missing)}/{len(ids)} requirements have a test")
    for i in missing:
        print(f"  no test: {i} ({ids[i]})")
    for i in unknown:
        print(f"  test cites an unknown requirement: {i}")
    if (missing or unknown) and not args.warn:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
