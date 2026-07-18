"""Configuration loading with JSON < environment < CLI precedence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
import json
import os
from pathlib import Path
from typing import Any, Mapping, TypeVar


DEFAULT_QWEN_ENDPOINT = (
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)


@dataclass(frozen=True)
class ProviderConfig:
    endpoint: str
    model: str
    kind: str = "openai"
    api_key: str | None = None
    timeout_s: float = 45.0
    max_tokens: int = 1024
    max_response_bytes: int = 1_048_576

    def validate(self, name: str) -> None:
        _require_type(self.endpoint, str, f"{name}.endpoint")
        _require_type(self.model, str, f"{name}.model")
        _require_type(self.kind, str, f"{name}.kind")
        if self.api_key is not None:
            _require_type(self.api_key, str, f"{name}.api_key")
        _require_number(self.timeout_s, f"{name}.timeout_s")
        _require_int(self.max_tokens, f"{name}.max_tokens")
        _require_int(self.max_response_bytes, f"{name}.max_response_bytes")
        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError(f"{name}.endpoint must be an http(s) URL")
        if not self.model.strip():
            raise ValueError(f"{name}.model must not be empty")
        if self.kind not in {"openai", "sysop_bridge"}:
            raise ValueError(f"{name}.kind must be openai or sysop_bridge")
        if self.timeout_s <= 0:
            raise ValueError(f"{name}.timeout_s must be positive")
        if self.max_tokens < 1:
            raise ValueError(f"{name}.max_tokens must be positive")
        if not 1024 <= self.max_response_bytes <= 16 * 1024 * 1024:
            raise ValueError(
                f"{name}.max_response_bytes must be between 1024 and 16777216"
            )


@dataclass(frozen=True)
class LoopConfig:
    target_score: float = 10.0
    max_iterations: int = 6
    max_elapsed_s: float = 300.0
    critic_parse_retries: int = 1
    max_stagnant_iterations: int = 2
    generator_temperature: float = 0.35
    critic_temperature: float = 0.0

    def validate(self) -> None:
        _require_number(self.target_score, "loop.target_score")
        _require_int(self.max_iterations, "loop.max_iterations")
        _require_number(self.max_elapsed_s, "loop.max_elapsed_s")
        _require_int(self.critic_parse_retries, "loop.critic_parse_retries")
        _require_int(self.max_stagnant_iterations, "loop.max_stagnant_iterations")
        _require_number(self.generator_temperature, "loop.generator_temperature")
        _require_number(self.critic_temperature, "loop.critic_temperature")
        if self.target_score != 10:
            raise ValueError("loop.target_score must be exactly 10 for strict consensus")
        if self.max_iterations < 1:
            raise ValueError("loop.max_iterations must be positive")
        if self.max_elapsed_s <= 0:
            raise ValueError("loop.max_elapsed_s must be positive")
        if self.critic_parse_retries < 0:
            raise ValueError("loop.critic_parse_retries cannot be negative")
        if self.max_stagnant_iterations < 0:
            raise ValueError("loop.max_stagnant_iterations cannot be negative")


@dataclass(frozen=True)
class MemoryConfig:
    max_used_fraction: float = 0.88
    min_available_mb: float = 768.0
    max_gpu_used_fraction: float = 0.92
    monitor_required: bool = False
    tegrastats_interval_ms: int = 500
    sample_timeout_s: float = 1.5

    def validate(self) -> None:
        _require_number(self.max_used_fraction, "memory.max_used_fraction")
        _require_number(self.min_available_mb, "memory.min_available_mb")
        _require_number(self.max_gpu_used_fraction, "memory.max_gpu_used_fraction")
        _require_type(self.monitor_required, bool, "memory.monitor_required")
        _require_int(self.tegrastats_interval_ms, "memory.tegrastats_interval_ms")
        _require_number(self.sample_timeout_s, "memory.sample_timeout_s")
        for key in ("max_used_fraction", "max_gpu_used_fraction"):
            value = getattr(self, key)
            if not 0 < value <= 1:
                raise ValueError(f"memory.{key} must be in (0, 1]")
        if self.min_available_mb < 0:
            raise ValueError("memory.min_available_mb cannot be negative")
        if self.tegrastats_interval_ms < 100:
            raise ValueError("memory.tegrastats_interval_ms must be at least 100")
        if self.sample_timeout_s <= 0:
            raise ValueError("memory.sample_timeout_s must be positive")


@dataclass(frozen=True)
class AppConfig:
    qwen: ProviderConfig = field(
        default_factory=lambda: ProviderConfig(
            endpoint=DEFAULT_QWEN_ENDPOINT,
            model="qwen-plus",
        )
    )
    local: ProviderConfig = field(
        default_factory=lambda: ProviderConfig(
            endpoint="http://127.0.0.1:8080/v1",
            model="qwen2.5-3b-instruct-local",
            timeout_s=90.0,
            max_tokens=768,
        )
    )
    loop: LoopConfig = field(default_factory=LoopConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    cloud_failure_threshold: int = 2
    cloud_cooldown_s: float = 30.0
    cloud_retries: int = 0
    cloud_retry_delay_cap_s: float = 2.0
    fallback_retries: int = 1
    fallback_retry_delay_s: float = 0.25
    max_task_chars: int = 32_768
    max_rubric_chars: int = 8_192
    offline: bool = False

    def validate(self) -> None:
        self.qwen.validate("qwen")
        self.local.validate("local")
        if self.qwen.kind != "openai":
            raise ValueError("qwen.kind must be openai")
        self.loop.validate()
        self.memory.validate()
        _require_int(self.cloud_failure_threshold, "cloud_failure_threshold")
        _require_number(self.cloud_cooldown_s, "cloud_cooldown_s")
        _require_int(self.cloud_retries, "cloud_retries")
        _require_number(self.cloud_retry_delay_cap_s, "cloud_retry_delay_cap_s")
        _require_int(self.fallback_retries, "fallback_retries")
        _require_number(self.fallback_retry_delay_s, "fallback_retry_delay_s")
        _require_int(self.max_task_chars, "max_task_chars")
        _require_int(self.max_rubric_chars, "max_rubric_chars")
        _require_type(self.offline, bool, "offline")
        if self.cloud_failure_threshold < 1:
            raise ValueError("cloud_failure_threshold must be positive")
        if self.cloud_cooldown_s < 0:
            raise ValueError("cloud_cooldown_s cannot be negative")
        if self.cloud_retries < 0:
            raise ValueError("cloud_retries cannot be negative")
        if self.cloud_retry_delay_cap_s < 0:
            raise ValueError("cloud_retry_delay_cap_s cannot be negative")
        if self.fallback_retries < 0 or self.fallback_retries > 5:
            raise ValueError("fallback_retries must be between 0 and 5")
        if not 0 <= self.fallback_retry_delay_s <= 10:
            raise ValueError("fallback_retry_delay_s must be between 0 and 10")
        if not 1 <= self.max_task_chars <= 1_000_000:
            raise ValueError("max_task_chars must be between 1 and 1000000")
        if not 1 <= self.max_rubric_chars <= 100_000:
            raise ValueError("max_rubric_chars must be between 1 and 100000")

    def redacted_dict(self) -> dict[str, Any]:
        output = asdict(self)
        if output["qwen"].get("api_key"):
            output["qwen"]["api_key"] = "***"
        if output["local"].get("api_key"):
            output["local"]["api_key"] = "***"
        return output

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "AppConfig":
        """Load a config file, then overlay environment variables.

        Unknown JSON keys are rejected to catch deployment typos. Secrets should be
        supplied through QWEN_API_KEY/DASHSCOPE_API_KEY, not committed to JSON.
        """

        env = os.environ if environ is None else environ
        config = cls()
        if path:
            with Path(path).open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raise ValueError("configuration root must be a JSON object")
            _reject_json_secrets(raw)
            config = _merge_dataclass(config, raw, "")

        qwen_key = env.get("QWEN_API_KEY") or env.get("DASHSCOPE_API_KEY")
        config = replace(
            config,
            qwen=replace(
                config.qwen,
                api_key=qwen_key or config.qwen.api_key,
                endpoint=env.get("CONGLOMERAITE_QWEN_ENDPOINT", config.qwen.endpoint),
                model=env.get("CONGLOMERAITE_QWEN_MODEL", config.qwen.model),
            ),
            local=replace(
                config.local,
                kind=env.get("CONGLOMERAITE_LOCAL_KIND", config.local.kind),
                endpoint=env.get("CONGLOMERAITE_LOCAL_ENDPOINT", config.local.endpoint),
                model=env.get("CONGLOMERAITE_LOCAL_MODEL", config.local.model),
            ),
            offline=_env_bool(env, "CONGLOMERAITE_OFFLINE", config.offline),
        )
        config.validate()
        return config


T = TypeVar("T")


def _merge_dataclass(current: T, values: Mapping[str, Any], prefix: str) -> T:
    known = {item.name: item for item in fields(current)}
    unknown = set(values) - set(known)
    if unknown:
        key = sorted(unknown)[0]
        raise ValueError(f"unknown configuration key: {prefix}{key}")

    updates: dict[str, Any] = {}
    for key, value in values.items():
        existing = getattr(current, key)
        if hasattr(existing, "__dataclass_fields__"):
            if not isinstance(value, Mapping):
                raise ValueError(f"{prefix}{key} must be an object")
            updates[key] = _merge_dataclass(existing, value, f"{prefix}{key}.")
        else:
            updates[key] = value
    return replace(current, **updates)


def _env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean")


def _reject_json_secrets(raw: Mapping[str, Any]) -> None:
    for provider_name in ("qwen", "local"):
        value = raw.get(provider_name)
        if isinstance(value, Mapping) and "api_key" in value:
            raise ValueError(
                f"{provider_name}.api_key is forbidden in JSON; use an environment variable"
            )


def _require_type(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise ValueError(f"{name} must be {expected.__name__}")


def _require_number(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")


def _require_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be int")
