"""Run every quality gate the same way locally and in CI (engineering.md § 3-4).

uv run scripts/check.py            # all gates, fast ones first
uv run scripts/check.py --fast     # lint, types, unit tests
uv run scripts/check.py --python   # every Python gate (CI python job)
uv run scripts/check.py --viewer   # viewer gates only
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"


def run(name: str, cmd: list[str], cwd: Path = ROOT) -> bool:
    print(f"\n=== {name}: {' '.join(cmd)}", flush=True)
    t = time.perf_counter()
    ok = subprocess.run(cmd, cwd=cwd, check=False).returncode == 0
    print(f"--- {name}: {'ok' if ok else 'FAILED'} ({time.perf_counter() - t:.1f} s)", flush=True)
    return ok


def python_lint() -> list[tuple[str, list[str]]]:
    return [
        ("ruff check", ["ruff", "check", "."]),
        ("ruff format", ["ruff", "format", "--check", "."]),
        ("ty", ["ty", "check"]),
    ]


def python_rest() -> list[tuple[str, list[str]]]:
    py = sys.executable
    return [
        ("import-linter", ["lint-imports"]),
        ("tests + coverage", [py, str(ROOT / "scripts" / "coverage_gate.py")]),
        ("generated files up to date", [py, str(ROOT / "scripts" / "gen.py"), "--check"]),
        ("licences", [py, str(ROOT / "scripts" / "licences.py")]),
        ("traceability", [py, str(ROOT / "scripts" / "trace.py")]),
    ]


def viewer_gates() -> list[tuple[str, list[str]]]:
    npm = shutil.which("npm") or "npm"
    return [
        ("svelte-check", [npm, "run", "check"]),
        ("eslint + prettier", [npm, "run", "lint"]),
        ("vitest", [npm, "test"]),
        ("npm licences", [npm, "run", "licences"]),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fast", action="store_true", help="lint, types, unit tests")
    g.add_argument("--python", action="store_true", help="every Python gate")
    g.add_argument("--viewer", action="store_true", help="viewer gates only")
    args = ap.parse_args()

    gates: list[tuple[str, list[str], Path]] = []
    if not args.viewer:
        gates += [(n, c, ROOT) for n, c in python_lint()]
    if args.fast:
        gates.append(("unit tests", ["pytest", "-q", "packages"], ROOT))
    elif not args.viewer:
        gates += [(n, c, ROOT) for n, c in python_rest()]
    if args.viewer or not (args.fast or args.python):
        gates += [(n, c, VIEWER) for n, c in viewer_gates()]

    failed = [name for name, cmd, cwd in gates if not run(name, cmd, cwd)]
    print()
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print(f"All {len(gates)} gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
