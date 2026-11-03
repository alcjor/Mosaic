"""Download conformance fixture sources and verify them by SHA-256.

Fixture sources are never committed (docs/design.md, Implementation plan):
they are listed in conformance/fixtures/manifest.json, downloaded here into
conformance/fixtures/downloads/, and checked against their pinned hash.
A fixture whose licence is not confirmed is skipped.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "conformance" / "fixtures" / "manifest.json"
DOWNLOADS = REPO / "conformance" / "fixtures" / "downloads"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures = 0
    for item in manifest["fixtures"]:
        name = item["name"]
        if not item.get("licence_confirmed"):
            print(f"skip {name}: licence not confirmed")
            continue
        if not item.get("url") or not item.get("sha256"):
            print(f"skip {name}: no url or hash pinned yet")
            continue
        target = DOWNLOADS / name / item["file"]
        if not (target.exists() and sha256(target) == item["sha256"]):
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"fetch {name} <- {item['url']}")
            urllib.request.urlretrieve(item["url"], target)
        actual = sha256(target)
        if actual != item["sha256"]:
            print(f"FAIL {name}: sha256 {actual} != pinned {item['sha256']}", file=sys.stderr)
            failures += 1
        else:
            print(f"ok   {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
