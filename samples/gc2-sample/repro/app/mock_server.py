"""Scripted mock API server — the only network authority in this bundle.

Serves responses from fixture.json's ordered script per route. No timing
dependence: the response for call N is fixed by the script, and the server
binds an ephemeral port so parallel runs never collide.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start_mock(fixture):
    """Start the mock in-process (no startup race). Returns (server, port)."""
    call_counts = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self):
            if self.path == "/healthz":
                self._respond(200, {"ok": True})
                return
            key = f"{self.command} {self.path}"
            route = fixture["routes"].get(key)
            if route is None:
                self._respond(404, {"error": "no scripted route", "key": key})
                return
            with lock:
                i = call_counts.get(key, 0)
                call_counts[key] = i + 1
            script = route["script"]
            if i < len(script):
                step = script[i]
            elif route.get("repeat_last"):
                step = script[-1]
            else:
                step = {"status": 500, "json": {"error": "script exhausted"}}
            self._respond(step["status"], step.get("json", {}))

        def _respond(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _serve
        do_POST = _serve

        def log_message(self, *args):
            pass  # keep test output clean; the signature is the evidence

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]
