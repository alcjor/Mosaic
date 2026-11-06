"""Draw a pull request's overview sheet as SVG, from a small JSON file the pair fills in.

The sheet sits at the top of every PR body (see "Pull request bodies" in CLAUDE.md). It is
one picture in stacked panels: the slice, an open question if there is one, the change map
from spec sections to code to tests with numbered arrows, the "Done when" checks, the pair
loop's rounds, the assumptions, and the numbers. Colours come from design/tokens.json.

    uv run python scripts/pr_sheet.py sheet.json --out pr-sheet   # writes pr-sheet-light.svg
                                                                   # and pr-sheet-dark.svg

The output uses no fonts, images or scripts from outside, so GitHub shows it as an image.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

WIDTH = 800
PAD = 32
GAP = 20
INNER = WIDTH - 2 * PAD
SANS = "'IBM Plex Sans', -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace"

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "page": "#FFFFFF",
        "slab": "#0A2A5C",
        "slab-ink": "#FFFFFF",
        "slab-muted": "#9CC3E8",
        "panel": "#EAF2FB",
        "heading": "#0A2A5C",
        "ink": "#1B2A3D",
        "muted": "#3B4B5F",
        "accent": "#2F6DB5",
        "border": "#C9DCF0",
        "box": "#FFFFFF",
        "spec": "#0A2A5C",
        "code": "#2F6DB5",
        "test": "#14837F",
        "ok": "#55701F",
        "ok-tint": "#E6EDD3",
        "bad": "#8E2B20",
        "bad-tint": "#F6DAD5",
        "ask": "#7A5A0E",
        "ask-tint": "#FCEFCF",
        "ask-line": "#F2B630",
    },
    "dark": {
        "page": "#0A2A5C",
        "slab": "#061733",
        "slab-ink": "#FFFFFF",
        "slab-muted": "#9CC3E8",
        "panel": "#0C3168",
        "heading": "#FFFFFF",
        "ink": "#E6EEF8",
        "muted": "#9CC3E8",
        "accent": "#6FA8DC",
        "border": "#1F5296",
        "box": "#0A2A5C",
        "spec": "#9CC3E8",
        "code": "#6FA8DC",
        "test": "#5FC4BE",
        "ok": "#E6EDD3",
        "ok-tint": "#34461A",
        "bad": "#F6DAD5",
        "bad-tint": "#5E1C15",
        "ask": "#FCEFCF",
        "ask-tint": "#5C430A",
        "ask-line": "#F2B630",
    },
}

STATUS_LABEL = {"draft": "DRAFT", "ready": "READY", "parked": "NEEDS DECISION"}


def wrap(text: str, size: float, width: float, mono: bool = False) -> list[str]:
    """Split text into lines that fit `width` pixels at font `size`, by an average glyph width."""
    per_char = size * (0.6 if mono else 0.53)
    limit = max(8, int(width / per_char))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            while len(word) > limit:
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:limit])
                word = word[limit:]
            candidate = f"{line} {word}" if line else word
            if len(candidate) <= limit:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


@dataclass
class Canvas:
    theme: dict[str, str]
    parts: list[str] = field(default_factory=list)
    y: float = 0

    def add(self, svg: str) -> None:
        self.parts.append(svg)

    def text(
        self,
        x: float,
        y: float,
        s: str,
        size: float = 15,
        colour: str = "ink",
        weight: int = 400,
        mono: bool = False,
        anchor: str = "start",
        spacing: float = 0,
    ) -> None:
        family = MONO if mono else SANS
        extra = f' letter-spacing="{spacing}"' if spacing else ""
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{self.theme[colour]}" text-anchor="{anchor}"{extra}>'
            f"{escape(s)}</text>"
        )

    def lines(
        self,
        x: float,
        y: float,
        rows: list[str],
        size: float = 15,
        colour: str = "ink",
        weight: int = 400,
        mono: bool = False,
    ) -> float:
        """Draw wrapped rows from baseline y; return the y below the last row."""
        step = size * 1.4
        for i, row in enumerate(rows):
            self.text(x, y + i * step, row, size, colour, weight, mono)
        return y + len(rows) * step

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str,
        r: float = 6,
        stroke: str | None = None,
    ) -> None:
        line = f' stroke="{self.theme[stroke]}" stroke-width="1.5"' if stroke else ""
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" '
            f'fill="{self.theme[fill]}"{line}/>'
        )

    def chip(self, x: float, y: float, label: str, fg: str, bg: str) -> float:
        """A status chip with its top-left at (x, y); return its width."""
        w = len(label) * 7.4 + 16
        self.rect(x, y, w, 22, bg, r=4)
        self.text(x + 8, y + 15.5, label, 12, fg, 600, spacing=0.6)
        return w

    def panel(self, title: str, height: float) -> tuple[float, float]:
        """Draw a panel background and its label; return (content x, content top)."""
        self.rect(PAD, self.y, INNER, height, "panel")
        self.text(PAD + 20, self.y + 28, title.upper(), 12, "accent", 600, spacing=1.2)
        top = self.y + 44
        self.y += height + GAP
        return PAD + 20, top


def title_block(c: Canvas, d: dict) -> None:
    summary = wrap(d.get("summary", ""), 16, INNER - 40)
    title = wrap(d["title"], 24, INNER - 40)
    h = 118 + len(title) * 32 + len(summary) * 22 + 18
    c.rect(0, 0, WIDTH, h, "slab", r=0)
    c.text(PAD, 40, "MOSAIC", 13, "slab-muted", 700, spacing=2)
    if d.get("pr"):
        c.text(PAD + 74, 40, f"PR #{d['pr']}", 13, "slab-muted", 500, mono=True)
    status = d.get("status", "draft")
    tint = {"ready": ("ok", "ok-tint"), "parked": ("ask", "ask-tint")}.get(status, ("ink", "panel"))
    label = STATUS_LABEL.get(status, status.upper())
    c.chip(WIDTH - PAD - (len(label) * 7.4 + 16), 25, label, *tint)
    c.text(PAD, 82, d["slice"], 30, "slab-ink", 600, mono=True)
    y = c.lines(PAD, 118, title, 24, "slab-ink", 600)
    c.lines(PAD, y + 8, summary, 16, "slab-muted")
    c.y = h + GAP


def question_panel(c: Canvas, q: dict) -> None:
    """The open question: one branch per reading, each ending in what a reader sees."""
    text = wrap(q["text"], 17, INNER - 40)
    readings = q.get("readings", [])
    blocks = []
    for r in readings:
        given = wrap(f"Given {r['given']}", 14, INNER - 120)
        sees = wrap(f"A reader sees {r['observed']}", 14, INNER - 120)
        blocks.append((r["name"], given, sees))
    h = 70 + len(text) * 24 + sum(40 + (len(g) + len(s)) * 20 for _, g, s in blocks)
    top_y = c.y
    c.rect(PAD, c.y, INNER, h, "ask-tint")
    c.add(
        f'<rect x="{PAD}" y="{c.y:.1f}" width="6" height="{h:.1f}" fill="{c.theme["ask-line"]}"/>'
    )
    c.text(PAD + 24, c.y + 28, f"QUESTION FOR YOU · {q['section']}", 12, "ask", 700, spacing=1.2)
    y = c.lines(PAD + 24, c.y + 54, text, 17, "ask", 600)
    stem_x = PAD + 40
    for i, (name, given, sees) in enumerate(blocks):
        y += 16
        c.add(
            f'<path d="M{stem_x} {y - 18} V{y + 6} H{stem_x + 24}" fill="none" '
            f'stroke="{c.theme["ask"]}" stroke-width="1.5"/>'
        )
        c.text(stem_x + 32, y + 11, f"{chr(65 + i)}  {name}", 15, "ask", 700)
        y = c.lines(stem_x + 56, y + 32, given, 14, "ask")
        y = c.lines(stem_x + 56, y, sees, 14, "ask", 600)
    c.y = top_y + h + GAP


def change_map(c: Canvas, m: dict) -> None:
    """Spec sections, then code, then tests, with numbered arrows in the order given."""
    cols = [
        ("spec", "Spec", m.get("spec", [])),
        ("code", "Code", m.get("code", [])),
        ("test", "Tests", m.get("tests", [])),
    ]
    col_w, col_gap = 200, (INNER - 40 - 3 * 200) / 2
    boxes: dict[str, tuple[float, float, float, float]] = {}
    heights = []
    layout = []
    for ci, (kind, _, items) in enumerate(cols):
        x = PAD + 20 + ci * (col_w + col_gap)
        y = 0.0
        for item in items:
            label = wrap(item["label"], 13, col_w - 20, mono=kind != "spec")
            note = wrap(item.get("note", ""), 12, col_w - 20) if item.get("note") else []
            bh = 16 + len(label) * 18 + len(note) * 16
            layout.append((kind, x, y, bh, label, note, item["id"]))
            y += bh + 14
        heights.append(y)
    body = max(heights or [0])
    h = 44 + 26 + body + 10
    x0, top = c.panel("Change map", h)
    for ci, (_, name, _) in enumerate(cols):
        c.text(x0 + ci * (col_w + col_gap), top + 6, name, 13, "muted", 600)
    for kind, x, y, bh, label, note, ident in layout:
        by = top + 22 + y
        c.rect(x, by, col_w, bh, "box", stroke=kind)
        c.add(
            f'<rect x="{x:.1f}" y="{by:.1f}" width="4" height="{bh:.1f}" rx="2" '
            f'fill="{c.theme[kind]}"/>'
        )
        yy = c.lines(x + 14, by + 20, label, 13, "ink", 500, mono=kind != "spec")
        c.lines(x + 14, yy - 2, note, 12, "muted")
        boxes[ident] = (x, by, col_w, bh)
    placed: list[tuple[float, float]] = []
    for n, (a, b) in enumerate(m.get("arrows", []), start=1):
        if a not in boxes or b not in boxes:
            raise ValueError(f"arrow {n} names a box that is not in the map: {a} -> {b}")
        ax, ay, aw, ah = boxes[a]
        bx, by, _, bh = boxes[b]
        if ax == bx:
            # Same column: leave and re-enter on the right side, bowing out into the gap.
            x1, y1, x2, y2 = ax + aw, ay + ah / 2, bx + aw + 6, by + bh / 2
            bow = x1 + col_gap * 0.6
            p1, p2 = (bow, y1), (bow, y2)
        else:
            x1, y1, x2, y2 = ax + aw, ay + ah / 2, bx - 6, by + bh / 2
            mid = (x1 + x2) / 2
            p1, p2 = (mid, y1), (mid, y2)
        c.add(
            f'<path d="M{x1:.1f} {y1:.1f} C{p1[0]:.1f} {p1[1]:.1f} {p2[0]:.1f} {p2[1]:.1f} '
            f'{x2:.1f} {y2:.1f}" fill="none" stroke="{c.theme["muted"]}" stroke-width="1.5" '
            f'marker-end="url(#arrow)"/>'
        )
        cx, cy = _label_spot((x1, y1), p1, p2, (x2, y2), placed)
        placed.append((cx, cy))
    for n, (cx, cy) in enumerate(placed, start=1):
        c.add(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="10" fill="{c.theme["accent"]}" '
            f'stroke="{c.theme["panel"]}" stroke-width="3"/>'
        )
        c.text(cx, cy + 4.5, str(n), 12, "page", 700, anchor="middle")


def _bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def _label_spot(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    placed: list[tuple[float, float]],
) -> tuple[float, float]:
    """The point along the curve whose number badge stands furthest from those placed so far."""
    best, best_gap = _bezier(p0, p1, p2, p3, 0.5), -1.0
    for t in (0.5, 0.88, 0.3, 0.7, 0.12, 0.4, 0.6, 0.2, 0.8):
        x, y = _bezier(p0, p1, p2, p3, t)
        gap = min(((x - px) ** 2 + (y - py) ** 2 for px, py in placed), default=1e9)
        if gap >= 30**2:
            return x, y
        if gap > best_gap:
            best, best_gap = (x, y), gap
    return best


def done_when(c: Canvas, items: list[dict]) -> None:
    rows = [
        (
            wrap(i["item"], 15, INNER - 90),
            wrap(i.get("proof", ""), 12, INNER - 90, True),
            bool(i.get("ok")),
        )
        for i in items
    ]
    h = 44 + sum(14 + len(a) * 21 + len(b) * 17 for a, b, _ in rows) + 6
    x, y = c.panel("Done when", h)
    for item, proof, ok in rows:
        fg, bg = ("ok", "ok-tint") if ok else ("bad", "bad-tint")
        c.add(f'<circle cx="{x + 11}" cy="{y + 10}" r="11" fill="{c.theme[bg]}"/>')
        mark = (
            f"M{x + 6} {y + 10} l4 4 l7 -8"
            if ok
            else f"M{x + 7} {y + 6} l8 8 M{x + 15} {y + 6} l-8 8"
        )
        c.add(
            f'<path d="{mark}" fill="none" stroke="{c.theme[fg]}" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        yy = c.lines(x + 34, y + 15, item, 15, "ink", 500)
        yy = c.lines(x + 34, yy, proof, 12, "muted", mono=True)
        y = yy + 14 - 15


def pair_loop(c: Canvas, rounds: list[dict], verdict: str) -> None:
    """Rounds left to right, then the final verdict."""
    n = len(rounds)
    step = (INNER - 40) / max(n + 1, 2)
    texts = [
        (
            wrap(f"Verifier: {r.get('verifier', '')}", 12, step - 18),
            wrap(f"Reviewer: {r.get('reviewer', '')}", 12, step - 18),
        )
        for r in rounds
    ]
    body = max([(len(a) + len(b)) * 16 for a, b in texts] or [0])
    h = 44 + 40 + body + 24
    x, y = c.panel("Pair loop", h)
    line_y = y + 14
    c.add(
        f'<line x1="{x}" y1="{line_y}" x2="{x + step * n + 30}" y2="{line_y}" '
        f'stroke="{c.theme["border"]}" stroke-width="2"/>'
    )
    for i, (r, (ver, rev)) in enumerate(zip(rounds, texts, strict=True)):
        cx = x + i * step + 14
        c.add(f'<circle cx="{cx}" cy="{line_y}" r="14" fill="{c.theme["accent"]}"/>')
        c.text(cx, line_y + 5, f"R{r.get('n', i + 1)}", 12, "page", 700, anchor="middle")
        yy = c.lines(cx - 14, line_y + 38, ver, 12, "ink")
        c.lines(cx - 14, yy, rev, 12, "muted")
    fg, bg = {"PASS": ("ok", "ok-tint"), "BLOCKING": ("bad", "bad-tint")}.get(
        verdict, ("ask", "ask-tint")
    )
    c.chip(x + n * step + 4, line_y - 11, verdict, fg, bg)


def assumptions(c: Canvas, items: list[dict]) -> None:
    rows = [
        (wrap(a["decision"], 14, INNER - 260), a.get("section", ""), a.get("ruling", ""))
        for a in items
    ]
    h = 44 + sum(12 + len(r[0]) * 20 for r in rows) + 6
    x, y = c.panel("Assumptions the pair made", h)
    for text, section, ruling in rows:
        yy = c.lines(x, y + 14, text, 14, "ink")
        right = PAD + INNER - 20
        label = ruling.upper() or "?"
        chip_w = len(label) * 7.4 + 16
        c.text(right - chip_w - 12, y + 14, section, 12, "muted", mono=True, anchor="end")
        fg, bg = ("ok", "ok-tint") if ruling == "accept" else ("ask", "ask-tint")
        c.chip(right - chip_w, y, label, fg, bg)
        y = yy + 12 - 14


def numbers(c: Canvas, items: list[dict]) -> None:
    per = (INNER - 40) / max(len(items), 1)
    h = 44 + 56
    x, y = c.panel("Numbers", h)
    for i, item in enumerate(items):
        nx = x + i * per
        c.text(nx, y + 18, str(item["value"]), 20, "heading", 600, mono=True)
        c.text(nx, y + 40, item["label"], 12, "muted")


def render(d: dict, theme_name: str) -> str:
    c = Canvas(THEMES[theme_name])
    title_block(c, d)
    if d.get("question"):
        question_panel(c, d["question"])
    if d.get("map"):
        change_map(c, d["map"])
    if d.get("done_when"):
        done_when(c, d["done_when"])
    if d.get("rounds"):
        pair_loop(c, d["rounds"], d.get("verdict", "PASS"))
    if d.get("assumptions"):
        assumptions(c, d["assumptions"])
    if d.get("numbers"):
        numbers(c, d["numbers"])
    height = c.y + PAD - GAP
    t = c.theme
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height:.0f}" '
        f'viewBox="0 0 {WIDTH} {height:.0f}" role="img" '
        f'aria-label="{escape(d["slice"] + " " + d["title"], {chr(34): "&quot;"})}">'
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" '
        f'fill="{t["muted"]}"/></marker></defs>'
        f'<rect width="{WIDTH}" height="{height:.0f}" fill="{t["page"]}"/>'
    )
    return head + "".join(c.parts) + "</svg>\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sheet", type=Path, help="the sheet's JSON file")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("pr-sheet"),
        help="output path without extension; writes -light.svg and -dark.svg",
    )
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.sheet.read_text(encoding="utf-8"))
        for theme in THEMES:
            out = args.out.with_name(f"{args.out.name}-{theme}.svg")
            out.write_text(render(data, theme), encoding="utf-8", newline="\n")
            print(out)
    except (OSError, ValueError, KeyError) as e:
        print(f"pr_sheet: {args.sheet}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
