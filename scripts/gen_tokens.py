"""Generate viewer/src/design/tokens.css from design/tokens.json.

    uv run python scripts/gen_tokens.py           # write the CSS
    uv run python scripts/gen_tokens.py --check   # exit 1 if the CSS is out of date

Colours: the first theme is the default; the second ("dark") applies under
`prefers-color-scheme: dark` unless the page sets data-theme="light", and always
under data-theme="dark". Aliases "{name}" become var(--name).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "design" / "tokens.json"
TARGET = REPO / "viewer" / "src" / "design" / "tokens.css"
ALIAS = re.compile(r"^\{([A-Za-z0-9][A-Za-z0-9_.-]*)\}$")
KEBAB = re.compile(r"(?<!^)(?=[A-Z])")


def color(value: str) -> str:
    m = ALIAS.match(value)
    return f"var(--{m.group(1)})" if m else value.lower()


def length(value: Any) -> str:
    return f"{value}px" if isinstance(value, int | float) and value != 0 else str(value)


def render(tokens: dict[str, Any]) -> str:
    themes = [t["id"] for t in tokens["color"]["themes"]]
    first, others = themes[0], themes[1:]
    base: list[str] = []
    per_theme: dict[str, list[str]] = {t: [] for t in others}
    for tok in tokens["color"]["tokens"]:
        value = tok["value"]
        if isinstance(value, str):
            base.append(f"  --{tok['name']}: {color(value)};")
            continue
        base.append(f"  --{tok['name']}: {color(value[first])};")
        for theme in others:
            if theme in value and value[theme] != value[first]:
                per_theme[theme].append(f"  --{tok['name']}: {color(value[theme])};")

    for family in ("spacing", "radius"):
        for tok in tokens.get(family, {}).get("tokens", []):
            base.append(f"  --{tok['name']}: {length(tok['value'])};")
    for key, stack in tokens["type"]["families"].items():
        base.append(f"  --font-{key}: {stack};")

    out = [
        "/* Mosaic — generated from design/tokens.json by scripts/gen_tokens.py. Do not edit. */",
        "",
        f':root,\n:root[data-theme="{first}"] {{',
        *base,
        "}",
    ]
    for theme, lines in per_theme.items():
        if not lines:
            continue
        if theme == "dark":
            out += [
                "",
                "@media (prefers-color-scheme: dark) {",
                f'  :root:not([data-theme="{first}"]) {{',
                *["  " + line for line in lines],
                "  }",
                "}",
            ]
        out += ["", f':root[data-theme="{theme}"] {{', *lines, "}"]

    families = tokens["type"]["families"]
    for group in tokens["type"]["groups"]:
        for style in group["styles"]:
            family = style.get("family", group["family"])
            decl = [f"  font-family: var(--font-{family});"]
            for prop in ("fontSize", "lineHeight", "fontWeight", "letterSpacing"):
                if prop in style:
                    raw = style[prop]
                    val = str(raw) if prop in ("lineHeight", "fontWeight") else length(raw)
                    decl.append(f"  {KEBAB.sub('-', prop).lower()}: {val};")
            assert family in families, f"unknown family {family!r}"
            out += ["", f".{style['name']} {{", *decl, "}"]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    css = render(json.loads(SOURCE.read_text(encoding="utf-8")))
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != css:
            print(f"{TARGET.relative_to(REPO)} is out of date: run scripts/gen_tokens.py")
            return 1
        return 0
    TARGET.write_text(css, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
