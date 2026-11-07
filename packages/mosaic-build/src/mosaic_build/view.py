"""``mosaic view``: open the viewer page with one mosaic loaded, with no query server.

docs/design.md (Implementation plan: Viewer, "``mosaic view`` opens the page with a mosaic
loaded, no query server"); Specification 0.1, section 3.8.

:func:`checked_bytes` applies the reading rules (section 3.8, steps 1 to 3) to the file before
any page opens, with the reader of :mod:`mosaic_format.reader`: a missing file, or one the
rules refuse, is a :class:`ViewError` naming the file and what failed. The file is opened
read-only and immutable, and its bytes are read once; they are what the page gets, so the file
is never written and nothing beside it is created.

:func:`serve` then serves, on ``127.0.0.1`` and a free port, the built viewer
(``viewer/dist``, from ``bun run build``) and those bytes at ``/file/<name>``, read-only: only
``GET`` and ``HEAD`` of those files, nothing else. The page fetches the mosaic named by its
address (``?mosaic=file/<name>``) and opens it with the kit inside the page, which applies the
reading rules again (section 3.8); every query runs in the page. The server only hands out
files.

With a model directory (``mosaic view FILE --model DIR``, answer A on #117), :func:`checked_model`
reads the two files of section 6 once and checks each by its pinned SHA-256; a file that is
missing or has another hash is a :class:`ViewError` naming the file (and both hashes), and no
page opens. Those bytes are served at ``/model/<path>`` and the address names them
(``&model=model/``), so the page loads the model at runtime and ``find`` lists vector matches.
Nothing else in the directory is served. Without a model, the address names none and the page
searches by names and full text only (section 3.8).

With a view file (``mosaic view FILE --view VIEW``, plan M3.7), the command reads it once before
any page opens (:func:`checked_view`); a wrong one is M3.5's error and no page opens. The page
then gets its settings at ``/view.json`` (``ViewSettings.as_json``), read from the file again on
each request, and the address names them (``&view=view.json``). The page asks again every second
and is reshaped when they change, so a saved file reaches it without restarting the command
(docs/design.md, View file: "mosaic view watches it and reloads the page on save"). A file saved
with an error answers 422 with that error, ``{"error": ...}``, and the page keeps what it shows.
The view file is only read.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from mosaic_format.reader import FileRefusedError
from mosaic_format.reader import open as open_sealed

from mosaic_build import view_file
from mosaic_build.mosaic.vectors import MODEL

VIEWER_DIST = Path(__file__).resolve().parents[4] / "viewer" / "dist"
"""The built viewer of this checkout (``bun run build``)."""

HOST = "127.0.0.1"
"""The page is served to this machine only."""

FILE_PREFIX = "/file/"
"""Where the mosaic is served, under its own file name."""

MODEL_PREFIX = "/model/"
"""Where the model's files are served, each under its path in the model's repository."""

VIEW_PATH = "/view.json"
"""Where the view file's current settings are served, as JSON."""

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


class ViewError(Exception):
    """``mosaic view`` cannot open the page; the message names the file and what failed."""


def checked_bytes(path: Path) -> bytes:
    """The bytes of ``path`` once the reading rules (section 3.8, steps 1 to 3) accept it."""
    if not path.is_file():
        raise ViewError(f"{path}: no such file")
    data = path.read_bytes()
    try:
        with open_sealed(path):
            pass
    except FileRefusedError as e:
        raise ViewError(str(e)) from None
    if path.read_bytes() != data:
        raise ViewError(f"{path}: the file changed while it was being checked")
    return data


def checked_model(directory: Path) -> dict[str, bytes]:
    """The bytes of each model file of section 6 in ``directory``, by its path, once checked.

    Each file is read once and checked by its pinned SHA-256, so the bytes the page gets are the
    ones that were checked. A missing file or another hash is a :class:`ViewError`.
    """
    if not directory.is_dir():
        raise ViewError(f"{directory}: no such model directory (section 6)")
    files: dict[str, bytes] = {}
    for pinned in MODEL.files:
        path = directory / pinned.path
        try:
            data = path.read_bytes()
        except OSError as e:
            raise ViewError(
                f"{path}: model file {pinned.path} cannot be read: {e.strerror or e}"
            ) from None
        actual = hashlib.sha256(data).hexdigest()
        if actual != pinned.sha256:
            raise ViewError(
                f"{path}: model file {pinned.path} has SHA-256 {actual}, not the pinned "
                f"{pinned.sha256} (section 6)"
            )
        files[pinned.path] = data
    return files


def checked_view(path: Path) -> dict[str, object]:
    """The settings of the view file ``path``, as the page takes them, or a :class:`ViewError`."""
    try:
        return view_file.read(path).as_json()
    except OSError as e:
        raise ViewError(f"{path}: view file cannot be read: {e.strerror or e}") from None
    except ValueError as e:  # names the file, the line and the setting (M3.5)
        raise ViewError(str(e)) from None


def _view_answer(path: Path) -> tuple[int, bytes]:
    """The status and JSON body ``/view.json`` answers with, from the view file as it is now."""
    try:
        status, data = HTTPStatus.OK, checked_view(path)
    except ViewError as e:
        status, data = HTTPStatus.UNPROCESSABLE_CONTENT, {"error": str(e)}
    return status, json.dumps(data, ensure_ascii=False).encode("utf-8")


def viewer_dist(dist: Path | None = None) -> Path:
    """The built viewer's directory, or a :class:`ViewError` saying how to build it."""
    directory = VIEWER_DIST if dist is None else dist
    if not (directory / "index.html").is_file():
        raise ViewError(f"{directory}: the viewer is not built; run `bun run build` first")
    return directory.resolve()


def page_url(port: int, name: str, model: bool = False, view: bool = False) -> str:
    """The address of the viewer page with the mosaic ``name`` (the model, the view) loaded."""
    url = f"http://{HOST}:{port}/?mosaic={quote(FILE_PREFIX[1:] + quote(name), safe='')}"
    if model:
        url += f"&model={quote(MODEL_PREFIX[1:], safe='')}"
    if view:
        url += f"&view={quote(VIEW_PATH[1:], safe='')}"
    return url


def _handler(
    dist: Path, name: str, data: bytes, model: dict[str, bytes], view: Path | None
) -> type[BaseHTTPRequestHandler]:
    file_path = FILE_PREFIX + quote(name)
    model_paths = {MODEL_PREFIX + quote(path): body for path, body in model.items()}

    class Handler(BaseHTTPRequestHandler):
        server_version = "mosaic-view"
        sys_version = ""

        def _body(self) -> tuple[bytes, str] | None:
            path = urlsplit(self.path).path
            if path == VIEW_PATH and view is not None:
                return b"", "application/json"  # answered by _answer, from the file as it is now
            if path == file_path:
                return data, "application/vnd.sqlite3"
            if path in model_paths:
                return model_paths[path], "application/octet-stream"
            if path.startswith(MODEL_PREFIX):
                return None
            relative = unquote(path).lstrip("/") or "index.html"
            try:
                local = (dist / relative).resolve()
                if not local.is_relative_to(dist) or not local.is_file():
                    return None
            except OSError, ValueError:  # a name no file can have, such as one holding NUL
                return None
            kind = TYPES.get(local.suffix) or mimetypes.guess_type(local.name)[0]
            return local.read_bytes(), kind or "application/octet-stream"

        def _answer(self, with_body: bool) -> None:
            found = self._body()
            if found is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body, kind = found
            status = HTTPStatus.OK
            if view is not None and urlsplit(self.path).path == VIEW_PATH:
                status, body = _view_answer(view)
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if with_body:
                self.wfile.write(body)

        def do_GET(self) -> None:
            self._answer(True)

        def do_HEAD(self) -> None:
            self._answer(False)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


def serve(
    dist: Path,
    name: str,
    data: bytes,
    port: int = 0,
    model: dict[str, bytes] | None = None,
    view: Path | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Serve the viewer, the mosaic's bytes, the model's and the view file's settings.

    Runs in a background thread. Returns the server and the page's address; ``model`` is
    :func:`checked_model`'s result, and ``view`` a view file :func:`checked_view` accepted.
    """
    server = ThreadingHTTPServer((HOST, port), _handler(dist, name, data, model or {}, view))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="mosaic-view", daemon=True).start()
    return server, page_url(server.server_address[1], name, bool(model), view is not None)
