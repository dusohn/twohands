#!/usr/bin/env python3
"""Serve the cashflow page and write data/plans.json from the on-screen form."""

from __future__ import annotations

import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_jobis import save_plans

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_PUT(self) -> None:
        if self.path.split("?", 1)[0] != "/api/plans":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > 100_000:
            self._json(400, {"ok": False, "error": "요청 크기가 올바르지 않습니다."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            result = save_plans(payload)
        except (ValueError, json.JSONDecodeError, KeyError, TypeError) as error:
            self._json(400, {"ok": False, "error": str(error)})
            return
        self._json(200, result)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}/site/index.html", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
