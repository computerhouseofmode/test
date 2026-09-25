"""標準ライブラリだけで動く HTTP サーバー。"""

from __future__ import annotations

import json
import mimetypes
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import api

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 5 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "opteval"

    def log_message(self, fmt, *args):  # 静かにする（エラーのみ表示）
        pass

    # --- 応答 -----------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        self._send(status, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, msg: str):
        self._json({"error": msg}, status)

    def _run(self, fn):
        try:
            fn()
        except api.ApiError as e:
            self._error(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._error(500, f"内部エラー: {type(e).__name__}: {e}")

    # --- GET ------------------------------------------------------------
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/api/glasses":
            return self._run(lambda: self._json(api.glasses()))
        if path == "/api/examples":
            return self._run(lambda: self._json(api.examples()))
        if path.startswith("/api/examples/"):
            name = path[len("/api/examples/"):]
            return self._run(lambda: self._json(api.example(name)))
        self._error(404, "not found")

    def _static(self, rel: str):
        p = (STATIC / rel).resolve()
        if STATIC not in p.parents or not p.is_file():
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, p.read_bytes(), ctype)

    # --- POST -----------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._error(413, "リクエストが大きすぎます")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._error(400, "JSON を解釈できません")
        if path == "/api/analyze":
            return self._run(lambda: self._json(api.analyze(payload)))
        if path == "/api/optimize":
            return self._run(lambda: self._json(api.optimize(payload)))
        if path == "/api/report":
            def send_report():
                html = api.html_report(payload).encode()
                self._send(200, html, "text/html; charset=utf-8",
                           {"Content-Disposition": 'attachment; filename="report.html"'})
            return self._run(send_report)
        self._error(404, "not found")


def make_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def serve(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False) -> None:
    httpd = make_server(host, port)
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{httpd.server_address[1]}/"
    print(f"opteval Web UI: {url}  (Ctrl+C で終了)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
