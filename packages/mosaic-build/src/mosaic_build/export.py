"""``mosaic export``: the viewer page with a mosaic inside, as one HTML file (plan M3.8).

docs/design.md, Implementation plan, Viewer: "``mosaic export`` saves the same page with the
mosaic inside as one HTML file that opens offline with a double-click"; View file: ``search:
text`` (a few MB) or ``search: semantic`` (the embedding model inside, M3.9).

:func:`export` checks the mosaic by the reading rules first (section 3.8, steps 1 to 3, with
:func:`mosaic_build.view.checked_bytes`) and the view file with M3.5's reader; a refused
file, a wrong view file or a view file whose ``search`` is ``semantic`` (not built until M3.9)
is an :class:`ExportError` and nothing is written. Then it writes one new HTML file, never over
an existing one: the built viewer's page (``bun run build``) with its script and stylesheet
inlined, and one JSON element holding the mosaic's name and bytes, the view file's settings and
SQLite's WebAssembly, the bytes in base64. The page reads that element and fetches nothing
(``viewer/src/lib/exported.ts``); the kit inside opens the bytes by the reading rules, both
hashes checked. No embedding model and no ONNX Runtime are carried. The mosaic and the view
file are only read.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
from pathlib import Path

from mosaic_build import view as viewer
from mosaic_build import view_file

EXPORT_ID = "mosaic-export"
"""The id of the element that holds the export's data (``viewer/src/lib/exported.ts``)."""

_SCRIPT = re.compile(r'<script type="module" crossorigin src="\./(assets/[^"]+\.js)"></script>')
_STYLE = re.compile(r'<link rel="stylesheet" crossorigin href="\./(assets/[^"]+\.css)">')


class ExportError(Exception):
    """``mosaic export`` cannot write the file; the message names what failed and where."""


def _asset(dist: Path, pattern: re.Pattern[str], page: str, what: str) -> str:
    found = pattern.findall(page)
    if len(found) != 1:
        raise ExportError(f"{dist / 'index.html'}: expected one {what}, found {len(found)}")
    return (dist / found[0]).read_text(encoding="utf-8")


def _sqlite_wasm(dist: Path) -> bytes:
    found = sorted((dist / "assets").glob("sqlite3-*.wasm"))
    if len(found) != 1:
        raise ExportError(f"{dist / 'assets'}: expected one sqlite3-*.wasm, found {len(found)}")
    return found[0].read_bytes()


def _inline(text: str, tag: str, where: Path) -> str:
    """``text`` checked to stay inside one ``<tag>`` element of the page."""
    lowered = text.lower()
    if f"</{tag}" in lowered or ("<!--" in lowered and "<script" in lowered):
        raise ExportError(f"{where}: cannot be inlined in a <{tag}> element")
    return text


def page(name: str, data: bytes, settings: dict[str, object], dist: Path) -> bytes:
    """The export's HTML: the built page with the mosaic ``name`` (``data``) inside."""
    index = (dist / "index.html").read_text(encoding="utf-8")
    script = _inline(_asset(dist, _SCRIPT, index, "module script"), "script", dist)
    style = _inline(_asset(dist, _STYLE, index, "stylesheet"), "style", dist)
    payload = {
        "name": name,
        "mosaic": base64.b64encode(data).decode("ascii"),
        "view": settings,
        "sqlite": base64.b64encode(_sqlite_wasm(dist)).decode("ascii"),
    }
    # `<` never appears raw, so the JSON cannot end its element or open a comment.
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    out = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"    <title>{html.escape(name)} · Mosaic</title>\n"
        f"    <style>{style}</style>\n"
        f'    <script type="application/json" id="{EXPORT_ID}">{text}</script>\n'
        f'    <script type="module">{script}</script>\n'
        "  </head>\n"
        "  <body>\n"
        '    <div id="app"></div>\n'
        "  </body>\n"
        "</html>\n"
    )
    return out.encode("utf-8")


def export(source: Path, output: Path, view: Path | None = None, dist: Path | None = None) -> int:
    """Write the export of ``source`` to the new file ``output``; returns its size in bytes.

    Raises :class:`ExportError` (nothing written) for a refused mosaic, a wrong view file, a view
    file asking for ``search: semantic``, an existing ``output`` or an unbuilt viewer.
    """
    try:
        data = viewer.checked_bytes(source)
        built = viewer.viewer_dist(dist)
    except viewer.ViewError as e:
        raise ExportError(str(e)) from None
    try:
        settings = view_file.read(view).as_json()
    except OSError as e:
        raise ExportError(f"{view}: view file cannot be read: {e.strerror or e}") from None
    except ValueError as e:  # names the file, the line and the setting (M3.5)
        raise ExportError(str(e)) from None
    if settings["search"] != "text":
        where = "the default view file" if view is None else str(view)
        raise ExportError(
            f"{where}: view file: search is semantic; an export with search: semantic carries the "
            "embedding model and is not built yet (plan M3.9); set search: text"
        )
    if output.exists() or output.is_symlink():
        raise ExportError(f"{output}: exists; an export is never overwritten")
    body = page(source.name, data, settings, built)
    try:
        with output.open("xb") as handle:
            try:
                handle.write(body)
            except BaseException:
                handle.close()
                os.unlink(output)
                raise
    except FileExistsError:
        raise ExportError(f"{output}: exists; an export is never overwritten") from None
    except OSError as e:
        raise ExportError(f"{output}: cannot be written: {e.strerror or e}") from None
    return len(body)
