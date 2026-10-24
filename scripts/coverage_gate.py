"""Run the unit, contract and integration tests under branch coverage and enforce the
per-package thresholds of engineering.md § 4 (core ≥ 90 %, other packages ≥ 80 %)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THRESHOLDS = {
    "mosaic_core": 90.0,
    "mosaic_extractors": 80.0,
    "mosaic_server": 80.0,
    "mosaic_cli": 80.0,
    "mosaic_mock": 80.0,
}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "coverage.json"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov",
            "--cov-branch",
            f"--cov-report=json:{report}",
            "--cov-report=",
        ]
        if subprocess.run(cmd, cwd=ROOT, check=False).returncode != 0:
            return 1
        files = json.loads(report.read_text())["files"]
    ok = True
    for pkg, minimum in THRESHOLDS.items():
        cov = covered = 0
        for path, data in files.items():
            if f"/{pkg}/" in path.replace("\\", "/"):
                s = data["summary"]
                cov += s["num_statements"] + s["num_branches"]
                covered += s["covered_lines"] + s["covered_branches"]
        pct = 100.0 * covered / cov if cov else 100.0
        flag = "ok" if pct >= minimum else "BELOW"
        ok &= pct >= minimum
        print(f"{pkg:20s} {pct:5.1f} % (min {minimum:.0f} %) {flag}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
