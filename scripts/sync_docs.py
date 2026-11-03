"""Refresh docs/ from a Markdown export of the "Mosaic — Design and specification" Claude Doc.

    uv run python scripts/sync_docs.py <export.md>

Writes docs/design.md (whole doc), docs/spec-0.1.md (Part 5) and one file per ADR
in docs/adr/ (from Part 3). Diagrams the export drops are marked in place.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
DIAGRAM = re.compile(r"^&#91;embedded content: (.*)\\\]$", re.M)


def main(export: Path) -> int:
    text = export.read_text(encoding="utf-8")
    text = DIAGRAM.sub(r"> *Diagram not exported (see the Claude Doc): \1*", text)
    text = text.rstrip() + "\n"
    (DOCS / "design.md").write_text(text, encoding="utf-8")

    lines = text.split("\n")
    spec_start = next(i for i, line in enumerate(lines) if line.startswith("## Part 5"))
    (DOCS / "spec-0.1.md").write_text("\n".join(lines[spec_start:]), encoding="utf-8")

    adr_dir = DOCS / "adr"
    adr_dir.mkdir(exist_ok=True)
    for old in adr_dir.glob("ADR-*.md"):
        old.unlink()
    heads = [i for i, line in enumerate(lines) if line.startswith("### ")]
    for n, start in enumerate(heads):
        m = re.match(r"### (ADR-\d{3}): (.*)", lines[start])
        if not m:
            continue
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = ["# " + lines[start][4:]]
        for line in lines[start + 1 : end]:
            body.append("#" + line[3:] if line.startswith("####") else line)
        slug = re.sub(r"[^a-z0-9]+", "-", m.group(2).lower()).strip("-")
        (adr_dir / f"{m.group(1)}-{slug}.md").write_text(
            "\n".join(body).rstrip() + "\n", encoding="utf-8"
        )
        print(f"wrote docs/adr/{m.group(1)}-{slug}.md")
    print("wrote docs/design.md, docs/spec-0.1.md")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
