"""Tests for gai guide HTML generation."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from gai.cli import run
from gai.guide import guide_path, write_guide_html


def test_write_guide_html_chinese_initial(tmp_path: Path):
    out = tmp_path / "guide.html"
    path = write_guide_html(chinese=True, path=out)
    text = path.read_text(encoding="utf-8")
    assert 'data-lang="cn"' in text
    assert "gai User Guide" in text or "gai 使用指南" in text
    assert "initialLang" in text
    assert '"cn"' in text and '"en"' in text
    assert "btn-cn" in text and "btn-en" in text
    assert "btn-theme-light" in text and "btn-theme-dark" in text
    assert 'data-theme="dark"' in text or "data-theme" in text
    assert "gai-guide-theme" in text
    assert "drawer-root" in text
    assert "drawer-switch" in text
    assert "gai commit" in text
    assert "completion" in text
    assert "Register-ArgumentCompleter" not in text  # not the PS script


def test_write_guide_html_english_initial(tmp_path: Path):
    out = tmp_path / "guide-en.html"
    path = write_guide_html(chinese=False, path=out)
    text = path.read_text(encoding="utf-8")
    assert 'data-lang="en"' in text
    assert "What is gai?" in text or "overview_h" in text


def test_guide_cli_prints_file_url(tmp_path: Path, monkeypatch):
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = run(["guide", "--cn"])
    assert code == 0
    combined = out.getvalue() + err.getvalue()
    assert "guide.html" in combined
    assert "file://" in combined
    written = guide_path(tmp_path)
    assert written.is_file()
    html = written.read_text(encoding="utf-8")
    assert 'data-lang="cn"' in html
