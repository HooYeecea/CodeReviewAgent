"""Redact URL credentials at display/storage boundaries, never transport inputs."""
import re
from urllib.parse import urlsplit, urlunsplit

_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>]+")


def redact_urls(text: str) -> str:
    def clean(match):
        try:
            parts = urlsplit(match.group())
            netloc = parts.netloc.rsplit("@", 1)
            authority = "***@" + netloc[-1] if len(netloc) == 2 else parts.netloc
            return urlunsplit((parts.scheme, authority, parts.path,
                               "***" if parts.query else "", "***" if parts.fragment else ""))
        except ValueError:
            return "[redacted URL]"
    return _URL.sub(clean, text)
