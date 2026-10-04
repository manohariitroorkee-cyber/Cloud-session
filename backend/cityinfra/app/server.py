"""Local web server for the simple app (Python standard library only).

    python -m cityinfra.app            # opens http://127.0.0.1:8765 in the browser
    python -m cityinfra.app --port 9000 --no-browser

Serves the page from ./static and a small JSON API:
    GET  /api/modules              what can be designed, with plain steps
    GET  /api/options              choice lists (cables, materials, …) from the rule sets
    GET  /api/example/<module>     a ready-made example drawing
    POST /api/check/<module>       {features, settings, name} → plain-language results
    POST /api/design/drainage      {features, settings} → proposed sizes and levels for the new drains
    POST /api/report               {markdown, title} → printable HTML report
It listens on this computer only (127.0.0.1) unless --host is given.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import api
from .plain import report_page

STATIC = Path(__file__).parent / "static"
# Windows can map .js/.css to the wrong type from its registry; browsers then refuse to run the page
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


class Handler(BaseHTTPRequestHandler):
    server_version = "CityInfra/1.0"

    def log_message(self, fmt, *args):            # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):   # the browser left the page before the answer arrived
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                f = (STATIC / path[len("/static/"):]).resolve()
                if STATIC.resolve() not in f.parents or not f.is_file():
                    return self._json({"error": "not found"}, 404)
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, f.read_bytes(), ctype)
            if path == "/api/modules":
                return self._json(api.modules())
            if path == "/api/options":
                return self._json(api.options())
            if path.startswith("/api/example/"):
                return self._json(api.example(path.rsplit("/", 1)[1]))
            return self._json({"error": "not found"}, 404)
        except KeyError:
            return self._json({"error": "unknown module"}, 404)
        except Exception as e:                    # pragma: no cover – shown to the user, logged to console
            traceback.print_exc()
            return self._json({"error": f"The program hit an internal error: {e}"}, 500)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            if path == "/api/design/drainage":
                return self._json(api.design_drainage(payload))
            if path.startswith("/api/check/"):
                return self._json(api.check(path.rsplit("/", 1)[1], payload))
            if path == "/api/report":
                html = report_page(payload.get("markdown", ""), payload.get("title", "Design check report"))
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return self._json({"error": "not found"}, 404)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:                    # pragma: no cover
            traceback.print_exc()
            return self._json({"error": f"The program hit an internal error: {e}"}, 500)


def serve(port: int = 8765, open_browser: bool = True, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{httpd.server_address[1]}/"
    print(f"City Infrastructure Designer is running at {url}\nKeep this window open while you work. "
          "Close it (or press Ctrl+C) to stop.")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    return httpd


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="cityinfra.app", description="Start the City Infrastructure Designer in your browser.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)),
                    help="port (default 8765, or the PORT environment variable set by a hosting service)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (default 127.0.0.1 = this computer only). Use 0.0.0.0 only on a "
                         "server behind the office network or a login-protected reverse proxy: the app has no login")
    a = ap.parse_args(argv)
    if a.host not in ("127.0.0.1", "localhost"):
        print(f"WARNING: listening on {a.host} – anyone who can reach this address can use the app (it has no login).")
    httpd = serve(a.port, not a.no_browser, a.host)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
