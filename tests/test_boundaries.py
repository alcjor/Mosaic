"""Architecture guards that CI enforces on every change.

- Principle 9 / quality goal 8: no domain words in the format, the mosaic builder
  or the mosaic kit. The domain lives in patterns and tessera builders. Tessera
  builders live under ``mosaic_build/tessera/`` and are exempt.
- The kit never depends on Python code; Python and TypeScript meet only at the
  mosaic file and the conformance cases.
"""

import json
import re
from pathlib import Path

from tests.conftest import REPO

DOMAIN_WORDS = [
    "sensor",
    "plant",
    "spacecraft",
    "satellite",
    "telemetry",
    "telecommand",
    "procedure",
    "px4",
    "mavlink",
    "netflix",
    "chinook",
    "openflights",
    "airport",
    "airline",
    "temp-3",
    "temp_3",
    "mib",
    "scos",
]
NEUTRAL_ROOTS = [
    REPO / "packages" / "mosaic-format" / "src",
    REPO / "packages" / "mosaic-build" / "src",
    REPO / "kit" / "src",
]
EXEMPT = [REPO / "packages" / "mosaic-build" / "src" / "mosaic_build" / "tessera"]
SUFFIXES = {".py", ".ts", ".js", ".sql"}


def _neutral_files() -> list[Path]:
    files = []
    for root in NEUTRAL_ROOTS:
        for path in root.rglob("*"):
            if path.suffix in SUFFIXES and not any(path.is_relative_to(e) for e in EXEMPT):
                files.append(path)
    return files


def test_neutral_code_exists() -> None:
    assert _neutral_files(), "the domain-word lint found nothing to check"


def test_no_domain_words_in_format_builder_or_kit() -> None:
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in DOMAIN_WORDS) + r")\b", re.I)
    hits = []
    for path in _neutral_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if m := pattern.search(line):
                hits.append(f"{path.relative_to(REPO)}:{n}: {m.group(0)!r}")
    assert not hits, "domain words in domain-neutral code:\n" + "\n".join(hits)


def test_kit_has_no_python_or_viewer_dependency() -> None:
    pkg = json.loads((REPO / "kit" / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("peerDependencies", {})}
    assert "viewer" not in deps and "@mosaic/viewer" not in deps
    for path in (REPO / "kit" / "src").rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        assert "packages/" not in text and "../viewer" not in text, path
