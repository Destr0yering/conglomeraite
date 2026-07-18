"""Command-line entrypoint for one bounded ConglomerAIte workflow."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import sys
import tempfile

from .config import AppConfig
from .loop import RefinementLoop
from .memory import AutoMemoryProbe, MemoryGuard
from .providers import FailoverRouter, OpenAICompatibleProvider, SysopBridgeProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conglomeraite",
        description="Run the fault-tolerant Generator/Critic 10/10 loop.",
    )
    parser.add_argument("task", nargs="?", help="task text; reads stdin when omitted")
    parser.add_argument("--task-file", type=Path, help="read the task from this UTF-8 file")
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--rubric", help="additional evaluation rubric")
    parser.add_argument("--offline", action="store_true", default=None, help="force local model")
    parser.add_argument(
        "--require-memory-monitor",
        action="store_true",
        default=None,
        help="trip rather than run if no Jetson/Linux memory source is available",
    )
    parser.add_argument("--target-score", type=float, help="strict mode only accepts 10")
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--max-elapsed", type=float, metavar="SECONDS")
    parser.add_argument("--max-used-fraction", type=float)
    parser.add_argument("--min-available-mb", type=float)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="emit full result JSON")
    output.add_argument(
        "--journal-summary",
        action="store_true",
        help="emit one metadata-only JSON object; never emits task or model text",
    )
    parser.add_argument(
        "--result-file",
        type=Path,
        help="atomically write full result JSON mode 0600; parent must exist",
    )
    parser.add_argument(
        "--trace-file",
        type=Path,
        help="write privacy-safe metrics JSON (task/drafts are excluded)",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="print effective redacted configuration and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _apply_cli_overrides(AppConfig.load(args.config), args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 64

    if args.print_config:
        print(json.dumps(config.redacted_dict(), indent=2, sort_keys=True))
        return 0

    try:
        request = _read_task(
            args,
            max_task_chars=config.max_task_chars,
            max_rubric_chars=config.max_rubric_chars,
        )
    except (OSError, ValueError) as exc:
        print(f"task error: {exc}", file=sys.stderr)
        return 64
    if args.rubric is not None and len(args.rubric) > config.max_rubric_chars:
        print(
            f"task error: rubric exceeds {config.max_rubric_chars} character limit",
            file=sys.stderr,
        )
        return 64

    router = _build_router(config, cloud_allowed=request.cloud_allowed)
    with AutoMemoryProbe(config.memory) as probe:
        workflow = RefinementLoop(
            router,
            MemoryGuard(probe, config.memory),
            config.loop,
            rubric=args.rubric or request.rubric or "",
        )
        result = workflow.run(request.task)

    if args.result_file:
        try:
            _write_protected_json(args.result_file, result.to_dict())
        except OSError as exc:
            print(f"result write failed: {exc}", file=sys.stderr)
            return 74

    if args.trace_file:
        try:
            _write_protected_json(args.trace_file, result.to_dict(include_text=False))
        except OSError as exc:
            print(f"trace write failed: {exc}", file=sys.stderr)
            return 74

    if args.journal_summary:
        print(json.dumps(result.journal_dict(), separators=(",", ":"), sort_keys=True))
    elif args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif result.final_draft:
        print(result.final_draft)
        print(
            f"[{result.status}] score={result.final_score} calls={result.model_calls} "
            f"attempts={result.route_attempts}: {result.stop_reason}",
            file=sys.stderr,
        )
    else:
        print(f"[{result.status}] {result.stop_reason}", file=sys.stderr)

    return {
        "consensus": 0,
        "max_iterations": 2,
        "stagnated": 3,
        "deadline": 75,
        "circuit_breaker": 75,
        "provider_error": 69,
    }.get(result.status, 1)


@dataclass(frozen=True)
class TaskRequest:
    task: str
    rubric: str | None = None
    cloud_allowed: bool = True


def _read_task(
    args: argparse.Namespace,
    *,
    max_task_chars: int = 32_768,
    max_rubric_chars: int = 8_192,
) -> TaskRequest:
    if args.task_file and args.task:
        raise ValueError("use either positional task or --task-file, not both")
    if args.task_file:
        max_file_bytes = (max_task_chars + max_rubric_chars) * 4 + 4096
        raw = _read_limited_utf8(args.task_file, max_file_bytes)
        file_rubric = None
        cloud_allowed = True
        if args.task_file.suffix.lower() == ".json":
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("task"), str):
                raise ValueError("JSON task file must contain a string 'task' field")
            task = payload["task"]
            candidate_rubric = payload.get("rubric")
            if candidate_rubric is not None and not isinstance(candidate_rubric, str):
                raise ValueError("JSON task file 'rubric' must be a string")
            file_rubric = candidate_rubric
            candidate_cloud_allowed = payload.get("cloud_allowed", True)
            if type(candidate_cloud_allowed) is not bool:
                raise ValueError("JSON task file 'cloud_allowed' must be boolean")
            cloud_allowed = candidate_cloud_allowed
    elif args.task:
        task = args.task
        file_rubric = None
        cloud_allowed = True
    elif not sys.stdin.isatty():
        task = sys.stdin.read(max_task_chars + 1)
        file_rubric = None
        cloud_allowed = True
    else:
        raise ValueError("provide a positional task, --task-file, or piped stdin")
    if not task.strip():
        raise ValueError("task is empty")
    task = task.strip()
    if len(task) > max_task_chars:
        raise ValueError(f"task exceeds {max_task_chars} character limit")
    if file_rubric is not None and len(file_rubric) > max_rubric_chars:
        raise ValueError(f"rubric exceeds {max_rubric_chars} character limit")
    return TaskRequest(task, file_rubric, cloud_allowed)


def _apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    loop = config.loop
    memory = config.memory
    if args.target_score is not None:
        loop = replace(loop, target_score=args.target_score)
    if args.max_iterations is not None:
        loop = replace(loop, max_iterations=args.max_iterations)
    if args.max_elapsed is not None:
        loop = replace(loop, max_elapsed_s=args.max_elapsed)
    if args.max_used_fraction is not None:
        memory = replace(memory, max_used_fraction=args.max_used_fraction)
    if args.min_available_mb is not None:
        memory = replace(memory, min_available_mb=args.min_available_mb)
    if args.require_memory_monitor is not None:
        memory = replace(memory, monitor_required=args.require_memory_monitor)
    output = replace(
        config,
        loop=loop,
        memory=memory,
        offline=config.offline if args.offline is None else args.offline,
    )
    output.validate()
    return output


def _build_router(config: AppConfig, *, cloud_allowed: bool) -> FailoverRouter:
    provider_type = (
        SysopBridgeProvider if config.local.kind == "sysop_bridge" else OpenAICompatibleProvider
    )
    local = provider_type(
        name="sysop-bridge" if config.local.kind == "sysop_bridge" else "llama-safe",
        endpoint=config.local.endpoint,
        model=config.local.model,
        api_key=config.local.api_key,
        timeout_s=config.local.timeout_s,
        max_tokens=config.local.max_tokens,
        max_response_bytes=config.local.max_response_bytes,
    )
    primary = None
    if cloud_allowed and not config.offline and config.qwen.api_key:
        primary = OpenAICompatibleProvider(
            name="qwen-cloud",
            endpoint=config.qwen.endpoint,
            model=config.qwen.model,
            api_key=config.qwen.api_key,
            timeout_s=config.qwen.timeout_s,
            max_tokens=config.qwen.max_tokens,
            max_response_bytes=config.qwen.max_response_bytes,
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


def _read_limited_utf8(path: Path, max_bytes: int) -> str:
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"task file exceeds {max_bytes} byte limit")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("task file must be valid UTF-8") from exc


def _write_protected_json(path: Path, payload: dict[str, object]) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise OSError(f"result parent directory does not exist: {parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
