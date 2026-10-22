"""Compatibility shim — use ``gai.common.web.serve``."""
from gai.common.web.serve import open_path, serve_gai_page
__all__ = ["open_path", "serve_gai_page"]
