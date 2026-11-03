"""The design system is enforced: tokens.css is generated, the viewer uses only tokens.

See design/README.md. Stylelint (viewer/.stylelintrc.json) rejects raw colours and
lengths; these tests cover what it cannot.
"""

import json
import re
import subprocess
import sys

from tests.conftest import REPO

TOKENS = REPO / "design" / "tokens.json"
VIEWER_SRC = REPO / "viewer" / "src"


def _token_names() -> set[str]:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    names = {t["name"] for t in data["color"]["tokens"]}
    for family in ("spacing", "radius"):
        names |= {t["name"] for t in data.get(family, {}).get("tokens", [])}
    names |= {f"font-{key}" for key in data["type"]["families"]}
    return names


def test_token_names_are_unique_and_valid() -> None:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    names = [t["name"] for t in data["color"]["tokens"]]
    for family in ("spacing", "radius"):
        names += [t["name"] for t in data.get(family, {}).get("tokens", [])]
    assert len(names) == len(set(names)), "duplicate token names"
    assert all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", n) for n in names)


def test_every_token_has_a_usage_note() -> None:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    for family in ("color", "spacing", "radius"):
        for tok in data[family]["tokens"]:
            assert tok.get("usage"), f"{family} token {tok['name']} has no usage note"


def test_tokens_css_is_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_tokens.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _viewer_files() -> list:
    return [
        p
        for p in VIEWER_SRC.rglob("*")
        if p.suffix in {".svelte", ".css", ".ts"} and "design" not in p.parts
    ]


def test_viewer_uses_only_defined_tokens() -> None:
    names = _token_names()
    unknown = []
    for path in _viewer_files():
        for m in re.finditer(r"var\(--([A-Za-z0-9_.-]+)", path.read_text(encoding="utf-8")):
            if m.group(1) not in names:
                unknown.append(f"{path.relative_to(REPO)}: --{m.group(1)}")
    assert not unknown, "var() names that are not tokens:\n" + "\n".join(unknown)


def test_no_inline_styles_in_viewer() -> None:
    hits = [
        str(p.relative_to(REPO))
        for p in VIEWER_SRC.rglob("*.svelte")
        if re.search(r"\sstyle\s*=", p.read_text(encoding="utf-8"))
    ]
    assert not hits, "inline style= attributes bypass the lint; use classes: " + ", ".join(hits)
