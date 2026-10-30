"""Exercise the actual local report server without real credentials or a browser."""

from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from gai.common.web import serve


def test_report_server_only_serves_public_assets(tmp_path, monkeypatch):
    page = tmp_path / "usage-report.html"
    page.write_text("report", encoding="utf-8")
    (tmp_path / "usage-data.js").write_text("public-data", encoding="utf-8")
    (tmp_path / "graph-app.js").write_text("public-app", encoding="utf-8")
    (tmp_path / "config.toml").write_text("FAKE_SECRET", encoding="utf-8")
    (tmp_path / "commands.jsonl").write_text("private-history", encoding="utf-8")
    (tmp_path / "private.html").write_text("private", encoding="utf-8")

    def inspect(url):
        origin = f"http://{urlsplit(url).netloc}"
        for path, expected in (
            ("/usage-report.html", b"report"),
            ("/usage-data.js?t=123", b"public-data"),
            ("/graph-app.js", b"public-app"),
        ):
            with urlopen(origin + path, timeout=3) as response:
                assert response.read() == expected
        for path in (
            "/", "/config.toml", "/commands.jsonl", "/private.html",
            "/%63onfig.toml", "/../config.toml", "/%2e%2e/config.toml",
            "/x/../usage-data.js", "/usage-data.js/", "/.git/config",
        ):
            for method in ("GET", "HEAD"):
                try:
                    response = urlopen(Request(origin + path, method=method), timeout=3)
                except HTTPError as exc:
                    assert exc.code == 404
                    exc.close()
                else:
                    response.close()
                    raise AssertionError(f"Unexpected access: {method} {path}")
        return True

    monkeypatch.setattr(serve.webbrowser, "open", inspect)
    serve.serve_gai_page(page, hold_seconds=0)


def test_report_server_rejects_symlink_assets(tmp_path, monkeypatch):
    import pytest

    page = tmp_path / "guide.html"
    page.write_text("report", encoding="utf-8")
    secret = tmp_path / "config.toml"
    secret.write_text("FAKE_SECRET", encoding="utf-8")
    try:
        (tmp_path / "usage-data.js").symlink_to(secret)
    except OSError:
        pytest.skip("Symlinks unavailable on this host")

    def inspect(url):
        with pytest.raises(HTTPError) as caught:
            urlopen(url.replace("guide.html", "usage-data.js"), timeout=3)
        assert caught.value.code == 404
        caught.value.close()
        return True

    monkeypatch.setattr(serve.webbrowser, "open", inspect)
    serve.serve_gai_page(page, hold_seconds=0)
