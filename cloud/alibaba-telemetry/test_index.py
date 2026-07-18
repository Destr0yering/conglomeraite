from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
import time
import unittest


receiver = importlib.import_module("index")


class ReceiverTests(unittest.TestCase):
    secret = "a" * 32

    def setUp(self) -> None:
        os.environ["TELEMETRY_HMAC_SECRET"] = self.secret

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload, separators=(",", ":"))
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.secret.encode(),
            timestamp.encode() + b"." + body.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "headers": {
                "x-conglomeraite-timestamp": timestamp,
                "x-conglomeraite-signature": f"sha256={signature}",
            },
            "body": body,
        }

    @staticmethod
    def payload() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "event_id": "evt-42",
            "event_type": "route_changed",
            "observed_at": "2026-07-18T07:00:00Z",
            "node_id_hash": "a" * 64,
            "task_id_hash": "b" * 64,
            "route": "local_edge",
            "degraded": True,
        }

    def test_accepts_signed_metadata(self) -> None:
        response = receiver.handler(self.request(self.payload()), None)
        self.assertEqual(response["statusCode"], 202)

    def test_rejects_content_field_even_when_signed(self) -> None:
        payload = self.payload()
        payload["prompt"] = "sensitive"
        response = receiver.handler(self.request(payload), None)
        self.assertEqual(response["statusCode"], 400)

    def test_rejects_bad_signature(self) -> None:
        request = self.request(self.payload())
        request["headers"]["x-conglomeraite-signature"] = "sha256=" + "0" * 64
        response = receiver.handler(request, None)
        self.assertEqual(response["statusCode"], 401)


if __name__ == "__main__":
    unittest.main()
