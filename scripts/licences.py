"""Licence gate (D14): every runtime dependency of the Mosaic packages must offer a
permissive licence. Dev-only tools (the LinkML generator and its dependencies) are not
shipped and are not checked here; see docs/implementation-decisions.md."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPYLEFT = re.compile(r"\b(A|L)?GPL|General Public License", re.IGNORECASE)


def runtime_packages() -> list[str]:
    out = subprocess.run(
        [
            "uv",
            "export",
            "--all-packages",
            "--no-dev",
            "--no-hashes",
            "--no-emit-workspace",
            "--no-header",
            "--no-annotate",
            "--frozen",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    names = []
    for raw in out.splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "-e", ".")):
            names.append(re.split(r"[=<>;\[ ]", line, maxsplit=1)[0])
    return names


def main() -> int:
    names = runtime_packages()
    out = subprocess.run(
        ["pip-licenses", "--format=json", "--from=mixed", "--packages", *names],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    bad = []
    for pkg in json.loads(out):
        licences = [s.strip() for s in pkg["License"].split(";") if s.strip()]
        if licences and all(COPYLEFT.search(s) for s in licences):
            bad.append(f"{pkg['Name']} {pkg['Version']}: {pkg['License']}")
    print(f"{len(names)} runtime dependencies checked")
    for b in bad:
        print("copyleft only:", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
