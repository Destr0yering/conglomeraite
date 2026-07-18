"""Alibaba Function Compute Web Function adapter for the telemetry receiver."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import index


class ReceiverHandler(BaseHTTPRequestHandler):
    """Expose the existing signed handler through a minimal HTTP server."""

    server_version = "ConglomerAIteTelemetry/1.0"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path.rstrip("/") == "/healthz":
            self._send(200, {"status": "ok"})
            return
        self._send(405, {"message": "use POST for signed telemetry"})

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        raw_length = self.headers.get("content-length", "")
        try:
            length = int(raw_length)
        except ValueError:
            self._send(400, {"message": "invalid content-length"})
            return
        if length < 1 or length > index.MAX_BODY_BYTES:
            self._send(400, {"message": "body must be between 1 and 8192 bytes"})
            return

        event = {
            "headers": {key: value for key, value in self.headers.items()},
            "body": self.rfile.read(length),
        }
        response = index.handler(event, None)
        self.send_response(int(response["statusCode"]))
        for key, value in response.get("headers", {}).items():
            self.send_header(str(key), str(value))
        body = response.get("body", "").encode("utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # Function Compute already captures structured application events. Keep
        # the server access log concise and avoid logging headers or bodies.
        print(json.dumps({"log_event": "http.access", "message": format % args}))

    def _send(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.environ.get("PORT", "9000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ReceiverHandler)
    print(json.dumps({"log_event": "receiver.started", "port": port}))
    server.serve_forever()


if __name__ == "__main__":
    main()
