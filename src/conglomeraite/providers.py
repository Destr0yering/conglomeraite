"""Dependency-light model providers and cloud-to-edge failover routing."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import random
import socket
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping, Protocol, Sequence
from urllib import error, request


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    degraded: bool = False
    failover_reason: str | None = None
    attempts: int = 1
    providers_attempted: tuple[str, ...] = ()
    finish_reason: str | None = None


class ChatProvider(Protocol):
    name: str

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        timeout_s: float | None = None,
    ) -> Completion: ...


class ProviderError(RuntimeError):
    def __init__(
        self,
        provider: str,
        message: str,
        *,
        retryable: bool,
        retry_after_s: float | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable
        self.retry_after_s = retry_after_s
        self.__cause__ = cause


class AllProvidersFailed(ProviderError):
    def __init__(self, primary_error: ProviderError | None, fallback_error: ProviderError):
        primary = str(primary_error) if primary_error else "primary disabled"
        super().__init__(
            "router",
            f"primary failed ({primary}); fallback failed ({fallback_error})",
            retryable=primary_error.retryable if primary_error else fallback_error.retryable,
            retry_after_s=primary_error.retry_after_s if primary_error else fallback_error.retry_after_s,
            cause=fallback_error,
        )
        self.primary_error = primary_error
        self.fallback_error = fallback_error


@dataclass
class OpenAICompatibleProvider:
    name: str
    endpoint: str
    model: str
    api_key: str | None = None
    timeout_s: float = 45.0
    max_tokens: int = 1024
    max_response_bytes: int = 1_048_576
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    urlopen: Callable[..., object] = request.urlopen
    clock: Callable[[], float] = time.monotonic

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        timeout_s: float | None = None,
    ) -> Completion:
        payload = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(self.extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        http_request = request.Request(
            _completion_url(self.endpoint),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = self.clock()
        try:
            effective_timeout = self.timeout_s
            if timeout_s is not None:
                if timeout_s <= 0:
                    raise TimeoutError("request deadline exhausted")
                effective_timeout = min(effective_timeout, timeout_s)
            response = self.urlopen(http_request, timeout=effective_timeout)
            with response:
                declared_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
                if declared_length is not None:
                    try:
                        too_large = int(declared_length) > self.max_response_bytes
                    except (TypeError, ValueError):
                        too_large = False
                    if too_large:
                        raise ProviderError(
                            self.name,
                            f"response exceeds {self.max_response_bytes} byte limit",
                            retryable=False,
                        )
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise ProviderError(
                        self.name,
                        f"response exceeds {self.max_response_bytes} byte limit",
                        retryable=False,
                    )
        except error.HTTPError as exc:
            detail = _read_http_error(exc)
            retryable = exc.code in {408, 409, 425, 429} or 500 <= exc.code <= 599
            retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
            raise ProviderError(
                self.name,
                f"HTTP {exc.code}{': ' + detail if detail else ''}",
                retryable=retryable,
                retry_after_s=retry_after,
                cause=exc,
            ) from exc
        except (error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            raise ProviderError(
                self.name,
                f"network failure: {exc}",
                retryable=True,
                cause=exc,
            ) from exc
        except OSError as exc:
            raise ProviderError(
                self.name,
                f"transport failure: {exc}",
                retryable=True,
                cause=exc,
            ) from exc

        latency_ms = (self.clock() - started) * 1000
        try:
            body = json.loads(raw.decode("utf-8"))
            choice = body["choices"][0]
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty message content")
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None and not isinstance(finish_reason, str):
                raise ValueError("invalid finish_reason")
            usage = body.get("usage") or {}
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(
                self.name,
                f"invalid completion response: {exc}",
                retryable=False,
                cause=exc,
            ) from exc

        return Completion(
            text=text.strip(),
            provider=self.name,
            latency_ms=latency_ms,
            input_tokens=_optional_int(usage.get("prompt_tokens")),
            output_tokens=_optional_int(usage.get("completion_tokens")),
            providers_attempted=(self.name,),
            finish_reason=finish_reason,
        )


@dataclass
class SysopBridgeProvider:
    """Bounded adapter for SYSOP's advisory-only ``POST /qwen/agent`` API."""

    name: str
    endpoint: str
    model: str = "sysop-agents"
    api_key: str | None = None
    timeout_s: float = 90.0
    max_tokens: int = 768
    max_response_bytes: int = 1_048_576
    max_request_bytes: int = 65_536
    urlopen: Callable[..., object] = request.urlopen
    clock: Callable[[], float] = time.monotonic

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        timeout_s: float | None = None,
    ) -> Completion:
        role_id = _sysop_role(messages)
        task = "\n\n".join(
            f"{message.role.upper()}:\n{message.content}" for message in messages
        )
        payload = {
            "task": task,
            "role_id": role_id,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
        }
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self.max_request_bytes:
            raise ProviderError(
                self.name,
                f"request exceeds {self.max_request_bytes} byte SYSOP bridge limit",
                retryable=False,
            )
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = request.Request(
            _sysop_agent_url(self.endpoint),
            data=encoded,
            headers=headers,
            method="POST",
        )
        effective_timeout = self.timeout_s
        if timeout_s is not None:
            if timeout_s <= 0:
                raise ProviderError(
                    self.name, "request deadline exhausted", retryable=True
                )
            effective_timeout = min(effective_timeout, timeout_s)
        started = self.clock()
        try:
            response = self.urlopen(http_request, timeout=effective_timeout)
            with response:
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise ProviderError(
                        self.name,
                        f"response exceeds {self.max_response_bytes} byte limit",
                        retryable=False,
                    )
        except error.HTTPError as exc:
            detail = _read_http_error(exc)
            retryable = exc.code in {408, 409, 425, 429, 503, 504} or 500 <= exc.code <= 599
            raise ProviderError(
                self.name,
                f"HTTP {exc.code}{': ' + detail if detail else ''}",
                retryable=retryable,
                retry_after_s=_parse_retry_after(exc.headers.get("Retry-After")),
                cause=exc,
            ) from exc
        except (error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            raise ProviderError(
                self.name, f"network failure: {exc}", retryable=True, cause=exc
            ) from exc
        except OSError as exc:
            raise ProviderError(
                self.name, f"transport failure: {exc}", retryable=True, cause=exc
            ) from exc

        latency_ms = (self.clock() - started) * 1000
        try:
            body = json.loads(raw.decode("utf-8"))
            if body.get("status") != "ok":
                raise ValueError("bridge status is not ok")
            text = body["response"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty bridge response")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                self.name,
                f"invalid SYSOP bridge response: {exc}",
                retryable=False,
                cause=exc,
            ) from exc
        return Completion(
            text=text.strip(),
            provider=self.name,
            latency_ms=latency_ms,
            input_tokens=_optional_int(body.get("input_tokens")),
            output_tokens=_optional_int(body.get("output_tokens")),
            providers_attempted=(self.name,),
            finish_reason="stop",
        )


class FailoverRouter:
    """Try cloud first and degrade to edge when the cloud path is unhealthy.

    The primary circuit breaker is shared across generator and critic requests. It
    opens after ``failure_threshold`` failed requests, then permits a half-open
    probe after ``cooldown_s``. The fallback remains available throughout.
    """

    def __init__(
        self,
        primary: ChatProvider | None,
        fallback: ChatProvider,
        *,
        failure_threshold: int = 2,
        cooldown_s: float = 30.0,
        retries: int = 0,
        max_retry_delay_s: float = 2.0,
        fallback_retries: int = 1,
        fallback_retry_delay_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if retries < 0:
            raise ValueError("retries cannot be negative")
        if max_retry_delay_s < 0:
            raise ValueError("max_retry_delay_s cannot be negative")
        if fallback_retries < 0:
            raise ValueError("fallback_retries cannot be negative")
        if fallback_retry_delay_s < 0:
            raise ValueError("fallback_retry_delay_s cannot be negative")
        self.primary = primary
        self.fallback = fallback
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.retries = retries
        self.max_retry_delay_s = max_retry_delay_s
        self.fallback_retries = fallback_retries
        self.fallback_retry_delay_s = fallback_retry_delay_s
        self._clock = clock
        self._sleep = sleep
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()
        # llama.cpp on an 8 GB unified-memory Jetson is intentionally single-flight.
        self._fallback_lock = threading.Lock()

    @property
    def circuit_open(self) -> bool:
        with self._lock:
            return self._is_open_locked(self._clock())

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        timeout_s: float | None = None,
    ) -> Completion:
        route_started = self._clock()
        primary_error: ProviderError | None = None
        skip_reason: str | None = None
        providers_attempted: list[str] = []

        if self.primary is None:
            skip_reason = "cloud disabled"
        elif self._allow_primary():
            for attempt in range(self.retries + 1):
                providers_attempted.append(self.primary.name)
                try:
                    remaining = self._remaining_timeout(route_started, timeout_s)
                    result = self.primary.complete(
                        messages, temperature=temperature, timeout_s=remaining
                    )
                except ProviderError as exc:
                    primary_error = exc
                    if not exc.retryable or attempt >= self.retries:
                        break
                    # Small jitter prevents synchronized edge fleets from retrying together.
                    backoff = 0.25 * (2**attempt) + random.random() * 0.05
                    requested_delay = exc.retry_after_s or 0.0
                    delay = min(max(backoff, requested_delay), self.max_retry_delay_s)
                    self._bounded_sleep(delay, route_started, timeout_s)
                else:
                    self._record_primary_success()
                    return Completion(
                        text=result.text,
                        provider=result.provider,
                        latency_ms=(self._clock() - route_started) * 1000,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        degraded=False,
                        attempts=len(providers_attempted),
                        providers_attempted=tuple(providers_attempted),
                        finish_reason=result.finish_reason,
                    )
            self._record_primary_failure()
        else:
            skip_reason = "cloud circuit open"

        reason = str(primary_error) if primary_error else skip_reason
        fallback_error: ProviderError | None = None
        for attempt in range(self.fallback_retries + 1):
            providers_attempted.append(self.fallback.name)
            try:
                remaining = self._remaining_timeout(route_started, timeout_s)
                with self._fallback_lock:
                    result = self.fallback.complete(
                        messages, temperature=temperature, timeout_s=remaining
                    )
                break
            except ProviderError as exc:
                fallback_error = exc
                if not exc.retryable or attempt >= self.fallback_retries:
                    raise AllProvidersFailed(primary_error, exc) from exc
                self._bounded_sleep(
                    self.fallback_retry_delay_s,
                    route_started,
                    timeout_s,
                )
        else:  # pragma: no cover - the bounded loop always returns or raises
            assert fallback_error is not None
            raise AllProvidersFailed(primary_error, fallback_error)
        return Completion(
            text=result.text,
            provider=result.provider,
            latency_ms=(self._clock() - route_started) * 1000,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            degraded=self.primary is not None,
            failover_reason=reason,
            attempts=len(providers_attempted),
            providers_attempted=tuple(providers_attempted),
            finish_reason=result.finish_reason,
        )

    def _remaining_timeout(self, started: float, timeout_s: float | None) -> float | None:
        if timeout_s is None:
            return None
        remaining = timeout_s - (self._clock() - started)
        if remaining <= 0:
            raise ProviderError("router", "request deadline exhausted", retryable=True)
        return remaining

    def _bounded_sleep(self, delay: float, started: float, timeout_s: float | None) -> None:
        if timeout_s is None:
            self._sleep(delay)
            return
        remaining = self._remaining_timeout(started, timeout_s)
        assert remaining is not None
        self._sleep(min(delay, remaining))

    def _allow_primary(self) -> bool:
        now = self._clock()
        with self._lock:
            if self._opened_at is None:
                return True
            if now - self._opened_at >= self.cooldown_s:
                # Half-open: only one caller should perform the probe.
                self._opened_at = now
                return True
            return False

    def _is_open_locked(self, now: float) -> bool:
        return self._opened_at is not None and now - self._opened_at < self.cooldown_s

    def _record_primary_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def _record_primary_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()


def _read_http_error(exc: error.HTTPError) -> str:
    try:
        raw = exc.read(2048)
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(parsed, dict):
            error_body = parsed.get("error", parsed)
            if isinstance(error_body, dict):
                detail = error_body.get("message") or error_body.get("code")
                return str(detail)[:500] if detail else ""
        return str(parsed)[:500]
    except Exception:
        return ""


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return int(value) if isinstance(value, (int, float)) else None


def _completion_url(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _sysop_agent_url(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/qwen/agent"):
        return normalized
    return f"{normalized}/qwen/agent"


def _sysop_role(messages: Sequence[ChatMessage]) -> str:
    contract = "\n".join(
        message.content for message in messages if message.role == "system"
    ).lower()
    if "you are the generator" in contract:
        return "agency_ai_engineer"
    if (
        "you are the critic" in contract
        or "you are the independent critic" in contract
        or "convert the prior critic" in contract
    ):
        return "agency_code_reviewer"
    return "agency_ai_engineer"


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            return max(0.0, target.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None
