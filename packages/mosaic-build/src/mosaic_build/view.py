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
"""

from __future__ import annotations

import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from mosaic_format.reader import FileRefusedError
from mosaic_format.reader import open as open_sealed

VIEWER_DIST = Path(__file__).resolve().parents[4] / "viewer" / "dist"
"""The built viewer of this checkout (``bun run build``)."""

HOST = "127.0.0.1"
"""The page is served to this machine only."""

FILE_PREFIX = "/file/"
"""Where the mosaic is served, under its own file name."""

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


def viewer_dist(dist: Path | None = None) -> Path:
    """The built viewer's directory, or a :class:`ViewError` saying how to build it."""
    directory = VIEWER_DIST if dist is None else dist
    if not (directory / "index.html").is_file():
        raise ViewError(f"{directory}: the viewer is not built; run `bun run build` first")
    return directory.resolve()


def page_url(port: int, name: str) -> str:
    """The address of the viewer page with the mosaic ``name`` loaded."""
    return f"http://{HOST}:{port}/?mosaic={quote(FILE_PREFIX[1:] + quote(name), safe='')}"


def _handler(dist: Path, name: str, data: bytes) -> type[BaseHTTPRequestHandler]:
    file_path = FILE_PREFIX + quote(name)

    class Handler(BaseHTTPRequestHandler):
        server_version = "mosaic-view"
        sys_version = ""

        def _body(self) -> tuple[bytes, str] | None:
            path = urlsplit(self.path).path
            if path == file_path:
                return data, "application/vnd.sqlite3"
            relative = unquote(path).lstrip("/") or "index.html"
            local = (dist / relative).resolve()
            if not local.is_relative_to(dist) or not local.is_file():
                return None
            kind = TYPES.get(local.suffix) or mimetypes.guess_type(local.name)[0]
            return local.read_bytes(), kind or "application/octet-stream"

        def _answer(self, with_body: bool) -> None:
            found = self._body()
            if found is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body, kind = found
            self.send_response(HTTPStatus.OK)
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


def serve(dist: Path, name: str, data: bytes, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Serve the viewer and the mosaic's bytes in a background thread; the server and the URL."""
    server = ThreadingHTTPServer((HOST, port), _handler(dist, name, data))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="mosaic-view", daemon=True).start()
    return server, page_url(server.server_address[1], name)
