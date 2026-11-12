"""Atomic TOML writes shared by CLI configuration and the local editor."""
from __future__ import annotations

from datetime import date, datetime, time
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib


def config_lock(path: Path):
    from gai.common.config import CONFIG_DIR
    from gai.common.jsonl import log_lock
    # Project locks belong in the user's private cache, never in Git's worktree.
    if path.name == ".gai.toml":
        identity = os.path.normcase(str(path.resolve())).encode("utf-8")
        return log_lock(CONFIG_DIR / "locks" / hashlib.sha256(identity).hexdigest())
    return log_lock(path)


def encode_toml(data: dict) -> str:
    # Inline tables retain unknown fields, including nested tables, without a
    # new runtime dependency. Formatting/comments are intentionally normalized.
    def value(item):
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False).replace("\x7f", "\\u007f")
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, (int, float)):
            return repr(item)
        if isinstance(item, (datetime, date, time)):
            return item.isoformat()
        if isinstance(item, list):
            return "[" + ", ".join(value(v) for v in item) + "]"
        if isinstance(item, dict):
            return "{ " + ", ".join(f"{value(str(k))} = {value(v)}" for k, v in item.items()) + " }"
        raise ValueError("Unsupported TOML value")

    lines = ["# gai configuration"]
    for name, body in data.items():
        if not isinstance(body, dict):
            lines.append(f"{value(name)} = {value(body)}")
    for name, body in data.items():
        if isinstance(body, dict):
            lines.extend(["", f"[{value(name)}]"])
            lines.extend(f"{value(str(k))} = {value(v)}" for k, v in body.items())
    text = "\n".join(lines) + "\n"
    tomllib.loads(text)
    return text


def write_config(path: Path, data: dict) -> None:
    from gai.common.config import _tighten_config_permissions
    encoded = encode_toml(data)
    with config_lock(path):
        fd, name = tempfile.mkstemp(prefix=path.name + "-", suffix=".tmp", dir=path.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                _tighten_config_permissions(temp)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            _tighten_config_permissions(path)
        finally:
            temp.unlink(missing_ok=True)
