"""Measured single-agent versus swarm benchmark harness.

This module deliberately reports observations rather than asserting that the swarm
wins. Run the same JSONL task set on stable hardware/network conditions, then use
the emitted ratios and explicitly same-critic scores as submission evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Sequence

from .config import AppConfig
from .loop import (
    CRITIC_SYSTEM_PROMPT,
    DEFAULT_RUBRIC,
    GENERATOR_SYSTEM_PROMPT,
    RefinementLoop,
    parse_critic_evaluation,
)
from .memory import AutoMemoryProbe, HardwareCircuitOpen, MemoryGuard
from .providers import (
    ChatMessage,
    Completion,
    FailoverRouter,
    OpenAICompatibleProvider,
    ProviderError,
    SysopBridgeProvider,
)


@dataclass(frozen=True)
class WorkMetrics:
    model_calls: int
    route_attempts: int
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    usage_coverage: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark single-agent generation against the 10/10 swarm."
    )
    parser.add_argument("tasks", type=Path, help="JSONL rows with id, task, optional rubric")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--include-text",
        action="store_true",
        help="include task and generated text; default output uses hashes only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = AppConfig.load(args.config)
        if args.offline:
            from dataclasses import replace

            config = replace(config, offline=True)
        tasks = _load_tasks(args.tasks, config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark input error: {exc}", file=sys.stderr)
        return 64

    records: list[dict[str, object]] = []
    with AutoMemoryProbe(config.memory) as probe:
        guard = MemoryGuard(probe, config.memory)
        for row in tasks:
            try:
                records.append(
                    _benchmark_task(row, guard, config, include_text=args.include_text)
                )
            except (HardwareCircuitOpen, ProviderError) as exc:
                records.append(
                    {
                        "id": row["id"],
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                # Hardware pressure must stop the entire run, not just one task.
                if isinstance(exc, HardwareCircuitOpen):
                    break

    output = {
        "schema_version": "1.0",
        "description": (
            "Observed one-shot and budget-matched single-agent baselines versus swarm; "
            "same-critic post-hoc evaluator calls are excluded from work cost"
        ),
        "run_metadata": {
            "mode": _mode(config),
            "models": {"qwen": config.qwen.model, "local": config.local.model},
            "config": config.redacted_dict(),
            "evaluation": "same configured Critic/provider policy; no evaluator independence",
            "router_state": "fresh router/circuit per arm and evaluator call",
        },
        "records": records,
        "summary": _summarize(records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(output["summary"], indent=2, sort_keys=True))
    return 0 if all(item.get("status") == "ok" for item in records) else 1


def _benchmark_task(
    row: dict[str, str],
    guard: MemoryGuard,
    config: AppConfig,
    *,
    include_text: bool,
) -> dict[str, object]:
    task = row["task"]
    rubric = row.get("rubric") or DEFAULT_RUBRIC
    cloud_allowed = row.get("cloud_allowed", "true") == "true"

    baseline_started = time.monotonic()
    baseline_completion = _guarded_complete(
        _build_router(config, cloud_allowed=cloud_allowed),
        guard,
        "benchmark.baseline",
        [
            ChatMessage("system", GENERATOR_SYSTEM_PROMPT),
            ChatMessage(
                "user",
                f"TASK:\n{task}\n\nRUBRIC:\n{rubric}\n\nCreate the initial deliverable.",
            ),
        ],
        temperature=config.loop.generator_temperature,
    )
    baseline_wall_ms = (time.monotonic() - baseline_started) * 1000

    swarm = RefinementLoop(
        _build_router(config, cloud_allowed=cloud_allowed),
        guard,
        config.loop,
        rubric=rubric,
    ).run(task)
    if not swarm.final_draft:
        raise ProviderError("swarm", swarm.stop_reason, retryable=False)

    budget_output_tokens = swarm.output_tokens
    budget_baseline_text, budget_baseline_metrics = _run_budget_baseline(
        task,
        rubric,
        _build_router(config, cloud_allowed=cloud_allowed),
        guard,
        config,
        max_calls=max(1, swarm.model_calls),
        max_wall_ms=max(1.0, swarm.elapsed_ms),
        max_output_tokens=budget_output_tokens,
    )

    # This is a same-critic post-hoc evaluation with no evaluator independence.
    # Fresh routers isolate circuit state across all candidates.
    candidates = [
        ("one_shot_baseline", baseline_completion.text),
        ("budget_matched_single_agent", budget_baseline_text),
        ("swarm", swarm.final_draft),
    ]
    rotation = int(hashlib.sha256(row["id"].encode()).hexdigest(), 16) % len(candidates)
    candidates = candidates[rotation:] + candidates[:rotation]
    scores: dict[str, float | None] = {}
    evaluator_usage: list[bool] = []
    for label, candidate in candidates:
        judged = _guarded_complete(
            _build_router(config, cloud_allowed=cloud_allowed),
            guard,
            f"benchmark.judge.{label}",
            [
                ChatMessage("system", CRITIC_SYSTEM_PROMPT),
                ChatMessage(
                    "user",
                    f"TASK:\n{task}\n\nRUBRIC:\n{rubric}\n\nDRAFT TO EVALUATE:\n{candidate}",
                ),
            ],
            temperature=0.0,
        )
        evaluator_usage.append(
            judged.input_tokens is not None and judged.output_tokens is not None
        )
        scores[label] = parse_critic_evaluation(judged.text).score

    baseline_metrics = WorkMetrics(
        model_calls=1,
        route_attempts=baseline_completion.attempts,
        latency_ms=baseline_wall_ms,
        input_tokens=baseline_completion.input_tokens,
        output_tokens=baseline_completion.output_tokens,
        usage_coverage=(
            1.0
            if baseline_completion.input_tokens is not None
            and baseline_completion.output_tokens is not None
            else 0.0
        ),
    )
    swarm_metrics = WorkMetrics(
        model_calls=swarm.model_calls,
        route_attempts=swarm.route_attempts,
        latency_ms=swarm.elapsed_ms,
        input_tokens=swarm.input_tokens,
        output_tokens=swarm.output_tokens,
        usage_coverage=swarm.usage_coverage or 0.0,
    )
    record: dict[str, object] = {
        "id": row["id"],
        "status": "ok",
        "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
        "mode": _mode(config, cloud_allowed=cloud_allowed),
        "evaluation": {
            "design": "same-critic-post-hoc",
            "independent": False,
            "model_calls": len(evaluator_usage),
            "usage_coverage": sum(evaluator_usage) / len(evaluator_usage),
        },
        "one_shot_baseline": {
            "score": scores["one_shot_baseline"],
            "work": asdict(baseline_metrics),
        },
        "budget_matched_single_agent": {
            "score": scores["budget_matched_single_agent"],
            "budget": {
                "max_calls": swarm.model_calls,
                "max_wall_ms": swarm.elapsed_ms,
                "max_output_tokens": budget_output_tokens,
                "token_budget_enforced": budget_output_tokens is not None,
                "note": "in-flight requests are not cancelled, so wall/token ceilings are soft",
            },
            "work": asdict(budget_baseline_metrics),
        },
        "swarm": {
            "score": scores["swarm"],
            "stop_reason": swarm.stop_reason,
            "status": swarm.status,
            "work": asdict(swarm_metrics),
        },
        "comparison": {
            "swarm_vs_one_shot": _compare_pair(
                scores["swarm"], scores["one_shot_baseline"], swarm_metrics, baseline_metrics
            ),
            "swarm_vs_budget_matched": _compare_pair(
                scores["swarm"],
                scores["budget_matched_single_agent"],
                swarm_metrics,
                budget_baseline_metrics,
            ),
        },
    }
    if include_text:
        record["task"] = task
        record["one_shot_baseline"]["output"] = baseline_completion.text  # type: ignore[index]
        record["budget_matched_single_agent"]["output"] = budget_baseline_text  # type: ignore[index]
        record["swarm"]["output"] = swarm.final_draft  # type: ignore[index]
    return record


def _guarded_complete(
    router: FailoverRouter,
    guard: MemoryGuard,
    stage: str,
    messages: Sequence[ChatMessage],
    *,
    temperature: float,
) -> Completion:
    guard.check(f"{stage}.before")
    completion = router.complete(messages, temperature=temperature)
    guard.check(f"{stage}.after")
    return completion


def _compare_pair(
    swarm_score: float | None,
    baseline_score: float | None,
    swarm: WorkMetrics,
    baseline: WorkMetrics,
) -> dict[str, float | None]:
    quality_gain = None
    if baseline_score is not None and swarm_score is not None:
        quality_gain = swarm_score - baseline_score
    return {
        "quality_score_gain": quality_gain,
        "latency_ratio_swarm_over_baseline": _ratio(swarm.latency_ms, baseline.latency_ms),
        "call_ratio_swarm_over_baseline": _ratio(swarm.model_calls, baseline.model_calls),
        "output_token_ratio_swarm_over_baseline": _ratio(
            swarm.output_tokens, baseline.output_tokens
        ),
        "swarm_quality_gain_per_extra_call": (
            _ratio(quality_gain, swarm.model_calls - baseline.model_calls)
            if quality_gain is not None
            else None
        ),
    }


def _summarize(records: list[dict[str, object]]) -> dict[str, object]:
    completed = [item for item in records if item.get("status") == "ok"]
    one_shot_gains = _comparison_values(completed, "swarm_vs_one_shot", "quality_score_gain")
    budget_gains = _comparison_values(
        completed, "swarm_vs_budget_matched", "quality_score_gain"
    )
    budget_latency_ratios = _comparison_values(
        completed, "swarm_vs_budget_matched", "latency_ratio_swarm_over_baseline"
    )
    budget_call_ratios = _comparison_values(
        completed, "swarm_vs_budget_matched", "call_ratio_swarm_over_baseline"
    )
    budget_output_token_ratios = _comparison_values(
        completed, "swarm_vs_budget_matched", "output_token_ratio_swarm_over_baseline"
    )
    noninferior = 0
    noninferior_and_faster = 0
    noninferior_and_fewer_output_tokens = 0
    for item in completed:
        comparison = item["comparison"]["swarm_vs_budget_matched"]  # type: ignore[index]
        gain = comparison["quality_score_gain"]
        latency_ratio = comparison["latency_ratio_swarm_over_baseline"]
        output_ratio = comparison["output_token_ratio_swarm_over_baseline"]
        if isinstance(gain, (int, float)) and gain >= 0:
            noninferior += 1
            if isinstance(latency_ratio, (int, float)) and latency_ratio < 1:
                noninferior_and_faster += 1
            if isinstance(output_ratio, (int, float)) and output_ratio < 1:
                noninferior_and_fewer_output_tokens += 1
    return {
        "tasks_total": len(records),
        "tasks_completed": len(completed),
        "swarm_vs_one_shot_quality_gain": _distribution(one_shot_gains),
        "swarm_vs_budget_matched_quality_gain": _distribution(budget_gains),
        "swarm_vs_budget_matched_latency_ratio": _distribution(budget_latency_ratios),
        "swarm_vs_budget_matched_call_ratio": _distribution(budget_call_ratios),
        "swarm_vs_budget_matched_output_token_ratio": _distribution(
            budget_output_token_ratios
        ),
        "budget_matched_swarm_win_rate": (
            sum(1 for gain in budget_gains if gain > 0) / len(budget_gains)
            if budget_gains
            else None
        ),
        "budget_matched_quality_noninferior_rate": (
            noninferior / len(completed) if completed else None
        ),
        "budget_matched_quality_noninferior_and_faster_rate": (
            noninferior_and_faster / len(completed) if completed else None
        ),
        "budget_matched_quality_noninferior_and_fewer_output_tokens_rate": (
            noninferior_and_fewer_output_tokens / len(completed) if completed else None
        ),
        "note": (
            "Fairness claims should use the budget-matched comparison on representative "
            "tasks; the one-shot comparison is descriptive only and no gain is assumed."
        ),
    }


def _run_budget_baseline(
    task: str,
    rubric: str,
    router: FailoverRouter,
    guard: MemoryGuard,
    config: AppConfig,
    *,
    max_calls: int,
    max_wall_ms: float,
    max_output_tokens: int | None,
) -> tuple[str, WorkMetrics]:
    started = time.monotonic()
    output = ""
    completions: list[Completion] = []
    for call_number in range(1, max_calls + 1):
        elapsed_ms = (time.monotonic() - started) * 1000
        consumed_output = sum(item.output_tokens or 0 for item in completions)
        if completions and (
            elapsed_ms >= max_wall_ms
            or (max_output_tokens is not None and consumed_output >= max_output_tokens)
        ):
            break
        if call_number == 1:
            messages = [
                ChatMessage("system", GENERATOR_SYSTEM_PROMPT),
                ChatMessage(
                    "user",
                    f"TASK:\n{task}\n\nRUBRIC:\n{rubric}\n\nCreate the initial deliverable.",
                ),
            ]
        else:
            messages = [
                ChatMessage(
                    "system",
                    "You are one self-refining agent. Independently inspect your prior answer "
                    "against the task and rubric, then return a corrected replacement. Do not "
                    "emit analysis, a score, or fabricated evidence.",
                ),
                ChatMessage(
                    "user",
                    f"TASK:\n{task}\n\nRUBRIC:\n{rubric}\n\nPRIOR ANSWER:\n{output}",
                ),
            ]
        completion = _guarded_complete(
            router,
            guard,
            f"benchmark.budget_single_agent.call_{call_number}",
            messages,
            temperature=config.loop.generator_temperature,
        )
        completions.append(completion)
        output = completion.text
    elapsed_ms = (time.monotonic() - started) * 1000
    return output, WorkMetrics(
        model_calls=len(completions),
        route_attempts=sum(item.attempts for item in completions),
        latency_ms=elapsed_ms,
        input_tokens=_sum_optional(item.input_tokens for item in completions),
        output_tokens=_sum_optional(item.output_tokens for item in completions),
        usage_coverage=(
            sum(
                item.input_tokens is not None and item.output_tokens is not None
                for item in completions
            )
            / len(completions)
            if completions
            else 0.0
        ),
    )


def _sum_optional(values) -> int | None:
    collected = list(values)
    return sum(collected) if collected and all(value is not None for value in collected) else None  # type: ignore[arg-type]


def _comparison_values(
    records: list[dict[str, object]], comparison: str, metric: str
) -> list[float]:
    values: list[float] = []
    for item in records:
        value = item["comparison"][comparison][metric]  # type: ignore[index]
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _load_tasks(path: Path, config: AppConfig) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("task"), str):
            raise ValueError(f"line {number}: expected object with string task")
        task = row["task"].strip()
        if not task:
            raise ValueError(f"line {number}: task is empty")
        if len(task) > config.max_task_chars:
            raise ValueError(f"line {number}: task exceeds {config.max_task_chars} characters")
        identifier = str(row.get("id", number))
        rubric = row.get("rubric")
        if rubric is not None and not isinstance(rubric, str):
            raise ValueError(f"line {number}: rubric must be a string")
        if rubric is not None and len(rubric) > config.max_rubric_chars:
            raise ValueError(
                f"line {number}: rubric exceeds {config.max_rubric_chars} characters"
            )
        cloud_allowed = row.get("cloud_allowed", True)
        if type(cloud_allowed) is not bool:
            raise ValueError(f"line {number}: cloud_allowed must be boolean")
        tasks.append(
            {
                "id": identifier,
                "task": task,
                "rubric": rubric or "",
                "cloud_allowed": "true" if cloud_allowed else "false",
            }
        )
    if not tasks:
        raise ValueError("task file contains no tasks")
    return tasks


def _build_router(config: AppConfig, *, cloud_allowed: bool = True) -> FailoverRouter:
    provider_type = (
        SysopBridgeProvider if config.local.kind == "sysop_bridge" else OpenAICompatibleProvider
    )
    local = provider_type(
        "sysop-bridge" if config.local.kind == "sysop_bridge" else "llama-safe",
        config.local.endpoint,
        config.local.model,
        config.local.api_key,
        config.local.timeout_s,
        config.local.max_tokens,
        config.local.max_response_bytes,
    )
    primary = None
    if cloud_allowed and not config.offline and config.qwen.api_key:
        primary = OpenAICompatibleProvider(
            "qwen-cloud",
            config.qwen.endpoint,
            config.qwen.model,
            config.qwen.api_key,
            config.qwen.timeout_s,
            config.qwen.max_tokens,
            config.qwen.max_response_bytes,
        )
    return FailoverRouter(
        primary,
        local,
        failure_threshold=config.cloud_failure_threshold,
        cooldown_s=config.cloud_cooldown_s,
        retries=config.cloud_retries,
        max_retry_delay_s=config.cloud_retry_delay_cap_s,
        fallback_retries=config.fallback_retries,
        fallback_retry_delay_s=config.fallback_retry_delay_s,
    )


def _mode(config: AppConfig, *, cloud_allowed: bool = True) -> str:
    if not cloud_allowed:
        return "task-local-only"
    if config.offline or not config.qwen.api_key:
        return "local-only"
    return "qwen-cloud-primary-with-local-fallback"


if __name__ == "__main__":
    raise SystemExit(main())
