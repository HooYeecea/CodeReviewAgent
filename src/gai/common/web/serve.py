"""Tiny local HTTP server to open .gai HTML pages reliably (vs file://)."""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


# Only generated reports and their known companion assets are public.
_REPORT_ASSETS = frozenset({
    "guide.html", "usage-report.html", "usage-data.js",
    "history-report.html", "history-data.js", "log-report.html",
    "graph-report.html", "graph-data.js", "graph-app.js",
})


class _ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, allowed_files: frozenset[str], **kwargs) -> None:
        self.allowed_files = allowed_files
        super().__init__(*args, **kwargs)

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        name = path.removeprefix("/")
        root = Path(self.directory).resolve()
        candidate = root / name
        if (
            name not in self.allowed_files
            or candidate.is_symlink()
            or candidate.resolve().parent != root
            or not candidate.is_file()
        ):
            self.send_error(404, "File not found")
            return None
        return super().send_head()


def serve_gai_page(
    html_path: Path,
    *,
    open_browser: bool = True,
    port: int = 0,
    hold_seconds: float = 3600,
) -> str:
    """Serve allowlisted report assets and return the HTTP URL for the page.

    Blocks the current thread for ``hold_seconds`` (default 1 hour) so the
    browser can keep refreshing assets. Pass a small value in tests.
    """
    html_path = html_path.resolve()
    root = html_path.parent
    if html_path.suffix.lower() != ".html":
        raise ValueError("Expected an HTML report")
    handler = functools.partial(
        _ReportHandler, directory=str(root),
        allowed_files=_REPORT_ASSETS | {html_path.name},
    )
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    httpd.allow_reuse_address = True
    bound_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{bound_port}/{quote(html_path.name)}"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        if open_browser:
            webbrowser.open(url)
        time.sleep(max(0.0, hold_seconds))
    finally:
        httpd.shutdown()
        httpd.server_close()
    return url


def open_path(path: Path, *, prefer_http: bool = False) -> str:
    """Open a local HTML path in the default browser.

    When ``prefer_http`` is True, start a short-lived local server (non-blocking
    for callers that only need the URL — use ``serve_gai_page`` to keep serving).
    """
    path = path.resolve()
    if prefer_http:
        # Fire-and-forget short serve in background; return URL immediately.
        url_box: list[str] = []

        def _run() -> None:
            url_box.append(
                serve_gai_page(path, open_browser=True, port=0, hold_seconds=7200)
            )

        threading.Thread(target=_run, daemon=True).start()
        # Give the server a moment to bind.
        time.sleep(0.15)
        if url_box:
            return url_box[0]
    uri = path.as_uri()
    webbrowser.open(uri)
    return uri
