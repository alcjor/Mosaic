"""``mosaic export``: the viewer page with a mosaic inside, as one HTML file (plan M3.8).

docs/design.md, Implementation plan, Viewer: "``mosaic export`` saves the same page with the
mosaic inside as one HTML file that opens offline with a double-click"; View file: ``search:
text`` (a few MB) or ``search: semantic`` (the embedding model inside, M3.9).

:func:`export` checks the mosaic by the reading rules first (section 3.8, steps 1 to 3, with
:func:`mosaic_build.view.checked_bytes`) and the view file as ``mosaic view --view`` does. A
refused file, a wrong view file, a view file whose ``search`` is ``semantic`` without the
model's directory (``--model DIR``) or a model file with another hash is an
:class:`ExportError`, and nothing is written. Then it writes one new HTML file, never over an
existing one: the built viewer's page (``bun run build``) with its script and stylesheet
inlined, and one JSON element holding the mosaic's name and bytes, the view file's settings and
SQLite's WebAssembly, the bytes gzip-compressed (no name, no time, so the same inputs give the
same file) and then base64. The page reads that element and fetches nothing
(``viewer/src/lib/exported.ts``); the kit inside opens the bytes by the reading rules, both
hashes checked. With ``search: semantic`` the element also holds the embedding model's two
files, checked by their pinned hashes, and ONNX Runtime's module and WebAssembly (plan M3.9), so
the page searches by vectors offline; with ``search: text`` it holds neither. The mosaic, the
view file and the model are only read.
"""

from __future__ import annotations

import base64
import gzip
import html
import json
import os
import re
from pathlib import Path

from mosaic_build import view as viewer
from mosaic_build import view_file
from mosaic_build.mosaic.vectors import MODEL

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


def _packed(data: bytes) -> str:
    """``data`` gzip-compressed with no name and no time, then base64: what the page unpacks."""
    return base64.b64encode(gzip.compress(data, compresslevel=6, mtime=0)).decode("ascii")


def _ort(dist: Path) -> dict[str, str]:
    """ONNX Runtime's module and WebAssembly from the built viewer, packed for the page."""
    assets = dist / "assets"
    module = sorted(assets.glob("ort.wasm.bundle.min-*.js"))
    wasm = sorted(assets.glob("ort-wasm-simd-threaded-*.wasm"))
    if len(module) != 1 or len(wasm) != 1:
        raise ExportError(
            f"{assets}: expected one ONNX Runtime module and one WebAssembly file, "
            f"found {len(module)} and {len(wasm)}"
        )
    return {"module": _packed(module[0].read_bytes()), "wasm": _packed(wasm[0].read_bytes())}


def page(
    name: str,
    data: bytes,
    settings: dict[str, object],
    dist: Path,
    model: dict[str, bytes] | None = None,
) -> bytes:
    """The export's HTML: the built page with the mosaic ``name`` (``data``) inside.

    With ``model`` (:func:`mosaic_build.view.checked_model`'s result), it also carries the model's
    two files and ONNX Runtime, so the page searches by vectors (``search: semantic``).
    """
    index = (dist / "index.html").read_text(encoding="utf-8")
    script = _inline(_asset(dist, _SCRIPT, index, "module script"), "script", dist)
    style = _inline(_asset(dist, _STYLE, index, "stylesheet"), "style", dist)
    payload = {
        "name": name,
        "mosaic": _packed(data),
        "view": settings,
        "sqlite": _packed(_sqlite_wasm(dist)),
    }
    if model is not None:
        payload["model"] = {
            "model": _packed(model[MODEL.model_file.path]),
            "tokenizer": _packed(model[MODEL.tokenizer.path]),
        }
        payload["ort"] = _ort(dist)
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


def default_output(source: Path) -> Path:
    """Where an export of ``source`` goes without ``-o``: its name with ``.html``, here (#131).

    Raises :class:`ExportError` for a path with no file name, such as ``.`` or ``/``.
    """
    if not source.name or source.name in (".", ".."):
        raise ExportError(f"{source}: no such file")
    return Path(Path(source.name).with_suffix(".html").name)


def export(
    source: Path,
    output: Path,
    view: Path | None = None,
    dist: Path | None = None,
    model: Path | None = None,
) -> int:
    """Write the export of ``source`` to the new file ``output``; returns its size in bytes.

    With ``search: semantic`` (the default) the export carries the embedding model from the
    directory ``model``, each file checked by its pinned SHA-256 as ``mosaic view --model``
    checks them, and ONNX Runtime; with ``search: text`` it carries neither.

    Raises :class:`ExportError` (nothing written) for a refused mosaic, a wrong view file, a
    missing, wrong or unasked-for model, an existing ``output`` or an unbuilt viewer.
    """
    try:
        data = viewer.checked_bytes(source)
        settings = view_file.read(None).as_json() if view is None else viewer.checked_view(view)
        built = viewer.viewer_dist(dist)
    except viewer.ViewError as e:  # a view file's names the file, the line and the setting (M3.5)
        raise ExportError(str(e)) from None
    try:
        source.name.encode("utf-8")
    except UnicodeEncodeError:
        shown = str(source).encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
        raise ExportError(
            f"{shown}: its file name is not UTF-8 text, so the page cannot name it"
        ) from None
    where = "the default view file" if view is None else str(view)
    files = None
    if settings["search"] == "semantic":
        if model is None:
            raise ExportError(
                f"{where}: view file: search is semantic, so the export carries the embedding "
                "model: give its directory with --model DIR (section 6), or set search: text"
            )
        try:
            files = viewer.checked_model(model)
        except viewer.ViewError as e:  # names the file and both hashes (section 6)
            raise ExportError(str(e)) from None
    elif model is not None:
        raise ExportError(
            f"{where}: view file: search is text, so the export carries no model; "
            "--model is for search: semantic"
        )
    if output.exists() or output.is_symlink():
        raise ExportError(f"{output}: exists; an export is never overwritten")
    body = page(source.name, data, settings, built, files)
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
