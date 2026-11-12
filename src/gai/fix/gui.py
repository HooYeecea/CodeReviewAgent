"""Authenticated loopback repair UI, using the configuration server's HTTP guards."""
from http.server import HTTPServer
import json
from pathlib import Path
import secrets
import threading
import webbrowser

from gai.setup.gui import ConfigHandler

ASSETS = {"/": ("fix.html", "text/html; charset=utf-8"),
          "/fix.js": ("fix.js", "text/javascript; charset=utf-8"),
          "/fix.css": ("fix.css", "text/css; charset=utf-8")}


class FixServer(HTTPServer):
    def __init__(self, session):
        self.session = session
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", 0), FixHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(15)
        return sock, address


class FixHandler(ConfigHandler):
    def dispatch(self, call):
        try:
            result = call()
        except (ValueError, RuntimeError) as exc:
            self.reply(400, {'error': str(exc)})
        except (OSError, TypeError, KeyError, AttributeError):
            self.reply(400, {'error': '无法完成修复操作，请检查文件权限、报告格式及修复记录。'})
        else:
            self.reply(200, result)

    def do_GET(self):
        if not self.permitted(api=self.path.startswith('/api/')):
            return
        if self.path in ASSETS:
            name, mime = ASSETS[self.path]
            self.reply(200, (Path(__file__).parents[1] / 'static' / name).read_bytes(), mime)
        elif self.path == '/api/state':
            self.dispatch(self.server.session.state)
        else:
            self.reply(404, {'error': '页面不存在'})

    def do_POST(self):
        if not self.permitted(api=True):
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.reply(415, {'error': '需要 JSON 请求'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 128_000 or self.headers.get('Transfer-Encoding'):
                raise ValueError()
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            self.reply(400, {'error': '请求格式或大小无效'})
            return
        session = self.server.session
        actions = {'/api/select': lambda: session.select(payload.get('report')),
                   '/api/validate': session.validate,
                   '/api/code': lambda: session.code(payload.get('id')),
                   '/api/generate': lambda: session.generate(payload.get('ids')),
                   '/api/apply': lambda: session.apply(payload.get('ticket')),
                   '/api/verify': session.verify}
        if self.path == '/api/close':
            self.reply(200, {'message': '服务已关闭，可以关闭此页面。'})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif self.path in actions:
            self.dispatch(actions[self.path])
        else:
            self.reply(404, {'error': '接口不存在'})


def serve_fix(session, *, open_browser=True):
    from gai.cli_common import console
    with FixServer(session) as server:
        url = server.origin + '/#' + server.token
        console.print('修复界面 / Repair editor: ' + url, markup=False)
        console.print('关闭页面不会停止服务；使用页面退出按钮或 Ctrl+C。', markup=False)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
