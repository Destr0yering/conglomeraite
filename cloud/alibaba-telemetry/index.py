"""Minimal signed, metadata-only Alibaba Function Compute HTTP receiver."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any


MAX_BODY_BYTES = 8 * 1024
MAX_CLOCK_SKEW_SECONDS = 300
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
ALLOWED_FIELDS = {
    "schema_version",
    "event_id",
    "event_type",
    "observed_at",
    "node_id_hash",
    "task_id_hash",
    "route",
    "role",
    "score",
    "latency_ms",
    "memory_used_fraction",
    "degraded",
    "stop_reason",
}
REQUIRED_FIELDS = {
    "schema_version",
    "event_id",
    "event_type",
    "observed_at",
    "node_id_hash",
}
ALLOWED_EVENT_TYPES = {"call_completed", "route_changed", "task_stopped"}
ALLOWED_ROUTES = {"qwen_cloud", "local_edge", "none"}
ALLOWED_ROLES = {"generator", "critic", "critic_repair", "router", "system"}


def handler(event: Any, context: Any) -> dict[str, Any]:
    """Verify a timestamped HMAC and log only an allowlisted scalar event."""

    del context
    try:
        headers, body = _http_request(event)
        secret = os.environ.get("TELEMETRY_HMAC_SECRET", "")
        if len(secret) < 32:
            return _response(503, "receiver secret is not configured")

        timestamp = headers.get("x-conglomeraite-timestamp", "")
        signature = headers.get("x-conglomeraite-signature", "")
        _verify_signature(secret.encode("utf-8"), timestamp, signature, body)
        payload = json.loads(body.decode("utf-8"))
        sanitized = _validate_payload(payload)

        # Function Compute captures stdout. No task, prompt, draft, critique,
        # credential, hostname, or raw node/task ID can pass the allowlist.
        print(
            json.dumps(
                {"log_event": "conglomeraite.telemetry.accepted", **sanitized},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return _response(202, "accepted", event_id=sanitized["event_id"])
    except AuthError as exc:
        return _response(401, str(exc))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        return _response(400, str(exc))


class AuthError(ValueError):
    pass


def _http_request(event: Any) -> tuple[dict[str, str], bytes]:
    if isinstance(event, bytes):
        event = event.decode("utf-8")
    if isinstance(event, str):
        event = json.loads(event)
    if not isinstance(event, dict):
        raise ValueError("HTTP event must be an object")

    raw_headers = event.get("headers", {})
    if not isinstance(raw_headers, dict):
        raise ValueError("headers must be an object")
    headers = {str(key).lower(): str(value) for key, value in raw_headers.items()}

    raw_body = event.get("body", "")
    if not isinstance(raw_body, (str, bytes)):
        raise ValueError("body must be text")
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    if event.get("isBase64Encoded") is True:
        try:
            body = base64.b64decode(body, validate=True)
        except ValueError as exc:
            raise ValueError("invalid base64 body") from exc
    if not body or len(body) > MAX_BODY_BYTES:
        raise ValueError("body must be between 1 and 8192 bytes")
    return headers, body


def _verify_signature(secret: bytes, timestamp: str, signature: str, body: bytes) -> None:
    try:
        timestamp_number = int(timestamp)
    except ValueError as exc:
        raise AuthError("invalid signature timestamp") from exc
    if abs(int(time.time()) - timestamp_number) > MAX_CLOCK_SKEW_SECONDS:
        raise AuthError("signature timestamp is outside the five-minute window")

    supplied = signature.removeprefix("sha256=").lower()
    expected = hmac.new(
        secret,
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise AuthError("invalid signature")


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("telemetry payload must be an object")
    unknown = set(payload) - ALLOWED_FIELDS
    missing = REQUIRED_FIELDS - set(payload)
    if unknown:
        raise ValueError(f"unknown or content-bearing field: {sorted(unknown)[0]}")
    if missing:
        raise ValueError(f"missing required field: {sorted(missing)[0]}")
    if payload["schema_version"] != "1.0":
        raise ValueError("unsupported schema_version")
    if not isinstance(payload["event_id"], str) or not SAFE_ID.fullmatch(payload["event_id"]):
        raise ValueError("event_id is invalid")
    if payload["event_type"] not in ALLOWED_EVENT_TYPES:
        raise ValueError("event_type is invalid")
    if not isinstance(payload["observed_at"], str) or not SAFE_ID.fullmatch(payload["observed_at"]):
        raise ValueError("observed_at must be a compact ISO-8601 timestamp")
    if not isinstance(payload["node_id_hash"], str) or not HEX_64.fullmatch(payload["node_id_hash"]):
        raise ValueError("node_id_hash must be a lowercase SHA-256 digest")
    if "task_id_hash" in payload and (
        not isinstance(payload["task_id_hash"], str)
        or not HEX_64.fullmatch(payload["task_id_hash"])
    ):
        raise ValueError("task_id_hash must be a lowercase SHA-256 digest")
    if "route" in payload and payload["route"] not in ALLOWED_ROUTES:
        raise ValueError("route is invalid")
    if "role" in payload and payload["role"] not in ALLOWED_ROLES:
        raise ValueError("role is invalid")
    _optional_number(payload, "score", 0.0, 10.0)
    _optional_number(payload, "latency_ms", 0.0, 3_600_000.0)
    _optional_number(payload, "memory_used_fraction", 0.0, 1.0)
    if "degraded" in payload and not isinstance(payload["degraded"], bool):
        raise ValueError("degraded must be boolean")
    if "stop_reason" in payload and (
        not isinstance(payload["stop_reason"], str)
        or not SAFE_ID.fullmatch(payload["stop_reason"])
    ):
        raise ValueError("stop_reason is invalid")
    return {key: payload[key] for key in sorted(payload)}


def _optional_number(payload: dict[str, Any], key: str, minimum: float, maximum: float) -> None:
    if key not in payload or payload[key] is None:
        return
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    if not minimum <= float(value) <= maximum:
        raise ValueError(f"{key} is outside its allowed range")


def _response(status: int, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps({"message": message, **extra}, separators=(",", ":")),
    }
