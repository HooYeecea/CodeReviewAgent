"""Loopback-only configuration editor; unrelated local files are never served."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading
import webbrowser

from gai.setup.editor import ConfigEditor

ASSETS = {"/": ("config.html", "text/html; charset=utf-8"),
          "/config.js": ("config.js", "text/javascript; charset=utf-8"),
          "/config.css": ("config.css", "text/css; charset=utf-8")}


class ConfigServer(HTTPServer):
    def __init__(self, editor: ConfigEditor):
        self.editor = editor
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", 0), ConfigHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(15)
        return sock, address


class ConfigHandler(BaseHTTPRequestHandler):
    server: ConfigServer

    def log_message(self, *args):
        # Request bodies, keys and session tokens must never reach access logs.
        pass

    def reply(self, code, body, mime="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def permitted(self, *, api=False):
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            self.reply(403, {"error": "非法来源"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            self.reply(403, {"error": "不允许跨站访问"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.reply(403, {"error": "不允许跨站访问"})
            return False
        if api and not secrets.compare_digest(self.headers.get("X-Gai-Token", "").encode(), self.server.token.encode()):
            self.reply(403, {"error": "会话无效，请使用终端提供的完整地址重新打开"})
            return False
        return True

    def do_GET(self):
        if not self.permitted(api=self.path.startswith("/api/")):
            return
        if self.path in ASSETS:
            name, mime = ASSETS[self.path]
            asset = Path(__file__).parents[1] / "static" / name
            self.reply(200, asset.read_bytes(), mime)
        elif self.path == "/api/state":
            self.dispatch(lambda: self.server.editor.state())
        else:
            self.reply(404, {"error": "页面不存在"})

    def dispatch(self, call):
        try:
            result = call()
        except (ValueError, RuntimeError) as exc:
            self.reply(400, {"error": str(exc)})
        except (OSError, TypeError, KeyError, AttributeError):
            self.reply(400, {"error": "无法完成操作，请检查配置格式、文件权限和环境变量访问权限"})
        else:
            self.reply(200, result)

    def do_POST(self):
        if not self.permitted(api=True):
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "需要 JSON 请求"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 128_000 or self.headers.get("Transfer-Encoding"):
                raise ValueError()
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "请求格式或大小无效"})
            return
        if self.path == "/api/preview":
            self.dispatch(lambda: self.server.editor.preview(payload))
        elif self.path == "/api/apply":
            self.dispatch(lambda: self.server.editor.apply(payload.get("ticket")))
        elif self.path == "/api/test":
            self.dispatch(lambda: self.server.editor.test_connection(payload.get("ticket")))
        elif self.path == "/api/close":
            self.reply(200, {"message": "配置服务已关闭，可以关闭此页面。"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.reply(404, {"error": "接口不存在"})


def serve_config(*, open_browser=True):
    from gai.common.git.core import GitError, run_git
    from gai.cli_common import console
    root = None
    try:
        result = run_git("rev-parse", "--show-toplevel", trace=False)
        if result.returncode == 0:
            root = Path(result.stdout.strip())
    except GitError:
        pass
    with ConfigServer(ConfigEditor(project_root=root)) as server:
        url = server.origin + "/#" + server.token
        console.print("配置界面 / Configuration editor: " + url, markup=False)
        console.print("关闭页面不会停止服务；点击页面中的“退出”或在此按 Ctrl+C。", markup=False)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
