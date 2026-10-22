"""URL helpers for local HTML reports."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def path_to_file_url(path: Path) -> str:
    """Return a browser-openable ``file://`` URL for a local path."""
    resolved = path.resolve()
    # pathlib.as_uri() already produces a correct file:// URL on Windows/POSIX.
    try:
        return resolved.as_uri()
    except ValueError:
        # Extremely rare non-absolute edge case
        text = str(resolved).replace("\\", "/")
        if not text.startswith("/"):
            text = "/" + text
        return "file://" + quote(text, safe="/:")
