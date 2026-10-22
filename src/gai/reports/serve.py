"""Tiny local HTTP server to open .gai HTML pages reliably (vs file://)."""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
import time
import webbrowser
from pathlib import Path


def serve_gai_page(
    html_path: Path,
    *,
    open_browser: bool = True,
    port: int = 0,
    hold_seconds: float = 3600,
) -> str:
    """Serve ``html_path.parent`` and return the http URL for the HTML file.

    Blocks the current thread for ``hold_seconds`` (default 1 hour) so the
    browser can keep refreshing assets. Pass a small value in tests.
    """
    html_path = html_path.resolve()
    root = html_path.parent
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    httpd.allow_reuse_address = True
    bound_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{bound_port}/{html_path.name}"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(url)
    try:
        time.sleep(max(0.0, hold_seconds))
    finally:
        httpd.shutdown()
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
