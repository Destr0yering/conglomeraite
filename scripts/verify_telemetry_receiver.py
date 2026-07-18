#!/usr/bin/env python3
"""Verify the deployed metadata-only telemetry receiver without model calls."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def request(url: str, *, body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, str]:
    method = "POST" if body is not None else "GET"
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint", help="Function Compute public endpoint")
    parser.add_argument("--secret-file", required=True, type=Path)
    args = parser.parse_args()

    secret = args.secret_file.read_text(encoding="utf-8").strip()
    if len(secret) < 32:
        raise SystemExit("secret must contain at least 32 characters")

    endpoint = args.endpoint.rstrip("/")
    health_status, health_body = request(f"{endpoint}/healthz")

    event_id = f"evt-{uuid.uuid4().hex[:24]}"
    payload = {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": "route_changed",
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "node_id_hash": hashlib.sha256(b"hackathon-nano-demo").hexdigest(),
        "route": "local_edge",
        "degraded": True,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    unsigned_status, unsigned_body = request(
        endpoint,
        body=raw,
        headers={"Content-Type": "application/json"},
    )

    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw, hashlib.sha256
    ).hexdigest()
    signed_status, signed_body = request(
        endpoint,
        body=raw,
        headers={
            "Content-Type": "application/json",
            "X-ConglomerAIte-Timestamp": timestamp,
            "X-ConglomerAIte-Signature": f"sha256={signature}",
        },
    )

    result = {
        "health": {"status": health_status, "body": health_body},
        "unsigned": {"status": unsigned_status, "body": unsigned_body},
        "signed": {"status": signed_status, "body": signed_body},
        "event_id": event_id,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if (health_status, unsigned_status, signed_status) == (200, 401, 202) else 1


if __name__ == "__main__":
    raise SystemExit(main())
