"""The docs in this repository are the source of truth, so their copies must not drift.

`docs/design.md` holds everything. `docs/spec-0.1.md` is its Part 5 on its own, and each file in
`docs/adr/` is one ADR from its Part 3, with headings raised one level. Edit `design.md` and the
copy together, in one pull request.
"""

import re

import pytest

from tests.conftest import REPO

DOCS = REPO / "docs"
ADR_HEADING = re.compile(r"### (ADR-\d{3}): (.*)")


def _design_lines() -> list[str]:
    return (DOCS / "design.md").read_text(encoding="utf-8").split("\n")


def _adrs() -> dict[str, str]:
    """Each ADR section of design.md as its own file: file name to expected text."""
    lines = _design_lines()
    heads = [i for i, line in enumerate(lines) if line.startswith("### ")]
    adrs = {}
    for n, start in enumerate(heads):
        m = ADR_HEADING.fullmatch(lines[start])
        if not m:
            continue
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = ["# " + lines[start][4:]]
        body += [
            "#" + line[3:] if line.startswith("####") else line for line in lines[start + 1 : end]
        ]
        slug = re.sub(r"[^a-z0-9]+", "-", m.group(2).lower()).strip("-")
        adrs[f"{m.group(1)}-{slug}.md"] = "\n".join(body).rstrip() + "\n"
    return adrs


def test_spec_is_part_5_of_the_design() -> None:
    lines = _design_lines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## Part 5"))
    expected = "\n".join(lines[start:])
    assert (DOCS / "spec-0.1.md").read_text(encoding="utf-8") == expected, (
        "docs/spec-0.1.md differs from Part 5 of docs/design.md; edit both together"
    )


def test_every_adr_in_the_design_has_its_file_and_no_other() -> None:
    assert sorted(p.name for p in (DOCS / "adr").glob("ADR-*.md")) == sorted(_adrs())


@pytest.mark.parametrize(("name", "expected"), sorted(_adrs().items()))
def test_adr_file_is_its_section_of_the_design(name: str, expected: str) -> None:
    assert (DOCS / "adr" / name).read_text(encoding="utf-8") == expected, (
        f"docs/adr/{name} differs from its section of docs/design.md; edit both together"
    )
