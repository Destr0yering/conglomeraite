import io
import json
from urllib import error
import unittest

from conglomeraite.providers import (
    ChatMessage,
    Completion,
    FailoverRouter,
    OpenAICompatibleProvider,
    ProviderError,
    SysopBridgeProvider,
)


class ScriptedProvider:
    def __init__(self, name: str, values: list[object]) -> None:
        self.name = name
        self.values = values
        self.calls = 0

    def complete(self, messages, *, temperature, timeout_s=None):
        value = self.values[self.calls]
        self.calls += 1
        if isinstance(value, BaseException):
            raise value
        return Completion(str(value), self.name, 1.0, providers_attempted=(self.name,))


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode()
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, amount=None):
        return self.body if amount is None else self.body[:amount]


class ProviderTests(unittest.TestCase):
    def test_sysop_bridge_maps_critic_to_review_role(self) -> None:
        captured = {}

        def urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse(
                {
                    "status": "ok",
                    "response": '{"score":10}',
                    "input_tokens": 42,
                }
            )

        provider = SysopBridgeProvider(
            "sysop", "http://127.0.0.1:8790", urlopen=urlopen
        )
        result = provider.complete(
            [
                ChatMessage("system", "You are the Critic. Score the draft."),
                ChatMessage("user", "DRAFT TO EVALUATE: ok"),
            ],
            temperature=0.0,
        )
        self.assertEqual(captured["url"], "http://127.0.0.1:8790/qwen/agent")
        self.assertEqual(captured["payload"]["role_id"], "agency_code_reviewer")
        self.assertIn("SYSTEM:", captured["payload"]["task"])
        self.assertEqual(result.text, '{"score":10}')
        self.assertEqual(result.input_tokens, 42)
        self.assertIsNone(result.output_tokens)

    def test_sysop_bridge_maps_generator_to_ai_role(self) -> None:
        captured = {}

        def urlopen(req, timeout):
            captured.update(json.loads(req.data.decode("utf-8")))
            return FakeResponse({"status": "ok", "response": "draft"})

        provider = SysopBridgeProvider(
            "sysop", "http://127.0.0.1:8790/qwen/agent", urlopen=urlopen
        )
        provider.complete(
            [
                ChatMessage(
                    "system",
                    "You are the Generator. Repair every item in the Critic feedback.",
                ),
                ChatMessage("user", "task"),
            ],
            temperature=0.2,
        )
        self.assertEqual(captured["role_id"], "agency_ai_engineer")

    def test_network_failure_degrades_to_local_and_opens_circuit(self) -> None:
        primary = ScriptedProvider(
            "cloud", [ProviderError("cloud", "offline", retryable=True)]
        )
        fallback = ScriptedProvider("local", ["draft", "critique"])
        router = FailoverRouter(primary, fallback, failure_threshold=1, cooldown_s=60)
        first = router.complete([ChatMessage("user", "x")], temperature=0)
        second = router.complete([ChatMessage("user", "x")], temperature=0)
        self.assertEqual(first.provider, "local")
        self.assertTrue(first.degraded)
        self.assertEqual(first.providers_attempted, ("cloud", "local"))
        self.assertEqual(second.providers_attempted, ("local",))
        self.assertEqual(primary.calls, 1)

    def test_nonretryable_error_does_not_consume_retries(self) -> None:
        primary = ScriptedProvider(
            "cloud", [ProviderError("cloud", "HTTP 401", retryable=False)]
        )
        fallback = ScriptedProvider("local", ["ok"])
        result = FailoverRouter(primary, fallback, retries=3).complete(
            [ChatMessage("user", "x")], temperature=0
        )
        self.assertEqual(primary.calls, 1)
        self.assertEqual(result.attempts, 2)

    def test_base_url_is_normalized_and_usage_is_captured(self) -> None:
        captured = {}

        def urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["auth"] = req.headers.get("Authorization")
            return FakeResponse(
                {
                    "choices": [
                        {"message": {"content": "hello"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                }
            )

        provider = OpenAICompatibleProvider(
            "qwen", "https://example.test/v1", "qwen", "secret", urlopen=urlopen
        )
        result = provider.complete([ChatMessage("user", "x")], temperature=0)
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["auth"], "Bearer secret")
        self.assertEqual(result.input_tokens, 3)
        self.assertEqual(result.output_tokens, 2)
        self.assertEqual(result.finish_reason, "stop")

    def test_http_error_classification(self) -> None:
        def make_provider(status):
            def urlopen(req, timeout):
                raise error.HTTPError(
                    req.full_url,
                    status,
                    "failed",
                    {},
                    io.BytesIO(b'{"error":{"message":"bad"}}'),
                )

            return OpenAICompatibleProvider("cloud", "https://x/v1", "q", urlopen=urlopen)

        with self.assertRaises(ProviderError) as unauthorized:
            make_provider(401).complete([ChatMessage("user", "x")], temperature=0)
        with self.assertRaises(ProviderError) as overloaded:
            make_provider(503).complete([ChatMessage("user", "x")], temperature=0)
        self.assertFalse(unauthorized.exception.retryable)
        self.assertTrue(overloaded.exception.retryable)

    def test_retry_after_is_honored_with_cap(self) -> None:
        primary = ScriptedProvider(
            "cloud",
            [
                ProviderError("cloud", "rate limited", retryable=True, retry_after_s=10),
                ProviderError("cloud", "still limited", retryable=True),
            ],
        )
        fallback = ScriptedProvider("local", ["ok"])
        sleeps = []
        router = FailoverRouter(
            primary,
            fallback,
            retries=1,
            max_retry_delay_s=1.5,
            sleep=sleeps.append,
        )
        router.complete([ChatMessage("user", "x")], temperature=0)
        self.assertEqual(sleeps, [1.5])

    def test_http_retry_after_is_parsed(self) -> None:
        def urlopen(req, timeout):
            raise error.HTTPError(
                req.full_url,
                429,
                "limited",
                {"Retry-After": "7"},
                io.BytesIO(b'{"error":{"message":"slow down"}}'),
            )

        provider = OpenAICompatibleProvider(
            "cloud", "https://x/v1", "qwen", urlopen=urlopen
        )
        with self.assertRaises(ProviderError) as caught:
            provider.complete([ChatMessage("user", "x")], temperature=0)
        self.assertEqual(caught.exception.retry_after_s, 7.0)

    def test_response_body_is_bounded(self) -> None:
        class LargeResponse(FakeResponse):
            def __init__(self):
                self.body = b"x" * 33
                self.headers = {}

        provider = OpenAICompatibleProvider(
            "cloud",
            "https://x/v1",
            "qwen",
            max_response_bytes=32,
            urlopen=lambda req, timeout: LargeResponse(),
        )
        # Constructor-level config normally enforces a >=1 KiB cap; this direct
        # unit uses 32 bytes to exercise the transport without allocating 1 MiB.
        with self.assertRaisesRegex(ProviderError, "response exceeds"):
            provider.complete([ChatMessage("user", "x")], temperature=0)

    def test_remaining_deadline_caps_transport_timeout(self) -> None:
        captured = {}

        def urlopen(req, timeout):
            captured["timeout"] = timeout
            return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        provider = OpenAICompatibleProvider(
            "cloud", "https://x/v1", "qwen", timeout_s=30, urlopen=urlopen
        )
        provider.complete(
            [ChatMessage("user", "x")], temperature=0, timeout_s=1.25
        )
        self.assertEqual(captured["timeout"], 1.25)

    def test_fallback_warmup_retry_is_bounded(self) -> None:
        fallback = ScriptedProvider(
            "local",
            [ProviderError("local", "warming", retryable=True), "ready"],
        )
        sleeps = []
        result = FailoverRouter(
            None,
            fallback,
            fallback_retries=1,
            fallback_retry_delay_s=0.1,
            sleep=sleeps.append,
        ).complete([ChatMessage("user", "x")], temperature=0, timeout_s=5)
        self.assertEqual(result.text, "ready")
        self.assertEqual(result.providers_attempted, ("local", "local"))
        self.assertEqual(sleeps, [0.1])


if __name__ == "__main__":
    unittest.main()
