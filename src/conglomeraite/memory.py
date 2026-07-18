"""Jetson-aware memory sampling and hardware circuit breaking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Protocol

from .config import MemoryConfig


_RAM_PATTERN = re.compile(r"\bRAM\s+(?P<used>\d+(?:\.\d+)?)/(?P<total>\d+(?:\.\d+)?)MB\b")


@dataclass(frozen=True)
class MemorySnapshot:
    source: str
    total_mb: float | None
    used_mb: float | None
    gpu_total_mb: float | None = None
    gpu_used_mb: float | None = None
    host_available_mb: float | None = None
    raw: str | None = None
    error: str | None = None
    sampled_at: float = 0.0

    @property
    def available_mb(self) -> float | None:
        if self.total_mb is None or self.used_mb is None:
            return None
        return max(0.0, self.total_mb - self.used_mb)

    @property
    def used_fraction(self) -> float | None:
        if not self.total_mb or self.used_mb is None:
            return None
        return self.used_mb / self.total_mb

    @property
    def gpu_used_fraction(self) -> float | None:
        if not self.gpu_total_mb or self.gpu_used_mb is None:
            return None
        return self.gpu_used_mb / self.gpu_total_mb

    @property
    def available(self) -> bool:
        return self.total_mb is not None and self.used_mb is not None


class MemoryProbe(Protocol):
    def snapshot(self) -> MemorySnapshot: ...

    def close(self) -> None: ...


class TegrastatsProbe:
    """Cache samples from one long-lived ``tegrastats`` process.

    Starting a new tegrastats process before every agent call is both slow and
    noisy. This probe starts it lazily, consumes stdout on a daemon thread, and
    reuses the latest complete RAM sample.
    """

    def __init__(
        self,
        *,
        interval_ms: int = 500,
        sample_timeout_s: float = 1.5,
        executable: str | None = None,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.interval_ms = interval_ms
        self.sample_timeout_s = sample_timeout_s
        self.executable = executable or shutil.which("tegrastats")
        self._popen = popen
        self._clock = clock
        self._process: subprocess.Popen[str] | None = None
        self._samples: queue.Queue[MemorySnapshot] = queue.Queue(maxsize=1)
        self._latest: MemorySnapshot | None = None
        self._lock = threading.Lock()
        self._closed = False

    @staticmethod
    def parse(line: str, *, sampled_at: float | None = None) -> MemorySnapshot | None:
        match = _RAM_PATTERN.search(line)
        if not match:
            return None
        return MemorySnapshot(
            source="tegrastats",
            total_mb=float(match.group("total")),
            used_mb=float(match.group("used")),
            raw=line.strip(),
            sampled_at=time.time() if sampled_at is None else sampled_at,
        )

    def snapshot(self) -> MemorySnapshot:
        if not self.executable:
            return _unavailable("tegrastats", "tegrastats executable not found", self._clock())
        self._ensure_started()
        try:
            sample = self._samples.get(timeout=self.sample_timeout_s)
            self._latest = sample
            return sample
        except queue.Empty:
            if self._latest is not None:
                return self._latest
            process = self._process
            if process is not None and process.poll() is not None:
                reason = f"tegrastats exited with status {process.returncode}"
            else:
                reason = "timed out waiting for tegrastats sample"
            return _unavailable("tegrastats", reason, self._clock())

    def close(self) -> None:
        with self._lock:
            self._closed = True
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._process is not None and self._process.poll() is None:
                return
            try:
                self._process = self._popen(
                    [self.executable, "--interval", str(self.interval_ms)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
            except OSError:
                self._process = None
                return
            thread = threading.Thread(target=self._consume, daemon=True)
            thread.start()

    def _consume(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            sample = self.parse(line, sampled_at=self._clock())
            if sample is None:
                continue
            try:
                self._samples.put_nowait(sample)
            except queue.Full:
                try:
                    self._samples.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._samples.put_nowait(sample)
                except queue.Full:
                    pass


class NvmlProbe:
    """Optional pynvml sampler; unavailable cleanly when the package/driver is absent."""

    def __init__(self, device_index: int = 0, clock: Callable[[], float] = time.time) -> None:
        self.device_index = device_index
        self._clock = clock
        self._nvml = None
        self._handle = None
        self._init_error: str | None = None

    def snapshot(self) -> MemorySnapshot:
        if self._nvml is None and self._init_error is None:
            try:
                import pynvml  # type: ignore[import-not-found]

                pynvml.nvmlInit()
                self._nvml = pynvml
                self._handle = pynvml.nvmlDeviceGetHandleByIndex(self.device_index)
            except Exception as exc:  # optional driver/package has many error classes
                self._init_error = str(exc)
        if self._nvml is None or self._handle is None:
            return _unavailable(
                "pynvml", self._init_error or "pynvml unavailable", self._clock()
            )
        try:
            info = self._nvml.nvmlDeviceGetMemoryInfo(self._handle)
            divisor = 1024 * 1024
            return MemorySnapshot(
                source="pynvml",
                total_mb=info.total / divisor,
                used_mb=info.used / divisor,
                gpu_total_mb=info.total / divisor,
                gpu_used_mb=info.used / divisor,
                sampled_at=self._clock(),
            )
        except Exception as exc:
            return _unavailable("pynvml", str(exc), self._clock())

    def close(self) -> None:
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
        self._nvml = None
        self._handle = None


class ProcMeminfoProbe:
    def __init__(
        self,
        path: str | Path = "/proc/meminfo",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self._clock = clock

    def snapshot(self) -> MemorySnapshot:
        try:
            values: dict[str, float] = {}
            with self.path.open("r", encoding="ascii") as handle:
                for line in handle:
                    key, raw = line.split(":", 1)
                    amount = raw.strip().split()[0]
                    values[key] = float(amount) / 1024.0
            total = values["MemTotal"]
            available = values.get("MemAvailable", values.get("MemFree", 0.0))
            return MemorySnapshot(
                source="proc_meminfo",
                total_mb=total,
                used_mb=max(0.0, total - available),
                sampled_at=self._clock(),
            )
        except (OSError, KeyError, ValueError, IndexError) as exc:
            return _unavailable("proc_meminfo", str(exc), self._clock())

    def close(self) -> None:
        return None


class CgroupMemoryProbe:
    """Read the active systemd/cgroup memory budget (cgroup v2 or v1)."""

    def __init__(
        self,
        root: str | Path = "/sys/fs/cgroup",
        proc_cgroup: str | Path = "/proc/self/cgroup",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(root)
        self.proc_cgroup = Path(proc_cgroup)
        self._clock = clock

    def snapshot(self) -> MemorySnapshot:
        candidates: list[tuple[Path, Path]] = []
        try:
            for line in self.proc_cgroup.read_text(encoding="ascii").splitlines():
                hierarchy, controllers, relative = line.split(":", 2)
                relative_path = relative.lstrip("/")
                if hierarchy == "0" and not controllers:  # cgroup v2
                    active = self.root / relative_path
                    candidates.append((active / "memory.current", active / "memory.max"))
                elif "memory" in controllers.split(","):  # cgroup v1
                    active = self.root / "memory" / relative_path
                    candidates.append(
                        (
                            active / "memory.usage_in_bytes",
                            active / "memory.limit_in_bytes",
                        )
                    )
        except (OSError, ValueError):
            pass
        candidates.extend(
            [
                (self.root / "memory.current", self.root / "memory.max"),
                (
                    self.root / "memory" / "memory.usage_in_bytes",
                    self.root / "memory" / "memory.limit_in_bytes",
                ),
            ]
        )
        errors: list[str] = []
        for current_path, max_path in candidates:
            try:
                current_raw = current_path.read_text(encoding="ascii").strip()
                max_raw = max_path.read_text(encoding="ascii").strip()
                if max_raw == "max":
                    continue
                current = float(current_raw) / (1024 * 1024)
                maximum = float(max_raw) / (1024 * 1024)
                # cgroup v1 sometimes represents unlimited as a huge sentinel.
                if maximum <= 0 or maximum >= 2**50 / (1024 * 1024):
                    continue
                return MemorySnapshot(
                    source="cgroup",
                    total_mb=maximum,
                    used_mb=current,
                    sampled_at=self._clock(),
                )
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        return _unavailable("cgroup", "; ".join(errors) or "no finite cgroup limit", self._clock())

    def close(self) -> None:
        return None


class AutoMemoryProbe:
    """Use the tightest host/cgroup budget and supplement it with optional NVML."""

    def __init__(self, config: MemoryConfig) -> None:
        self.system_probes: list[MemoryProbe] = [
            TegrastatsProbe(
                interval_ms=config.tegrastats_interval_ms,
                sample_timeout_s=config.sample_timeout_s,
            ),
            CgroupMemoryProbe(),
            ProcMeminfoProbe(),
        ]
        self.nvml = NvmlProbe()

    def snapshot(self) -> MemorySnapshot:
        errors: list[str] = []
        samples: list[MemorySnapshot] = []
        for probe in self.system_probes:
            sample = probe.snapshot()
            if sample.available:
                samples.append(sample)
            if sample.error:
                errors.append(f"{sample.source}: {sample.error}")
        gpu = self.nvml.snapshot()
        if not samples and gpu.available:
            return gpu
        if not samples:
            if gpu.error:
                errors.append(f"{gpu.source}: {gpu.error}")
            return _unavailable("auto", "; ".join(errors), time.time())

        # The binding budget is the source with the highest used fraction. This
        # catches both host unified-memory pressure and a tighter systemd MemoryMax.
        binding = max(samples, key=lambda item: item.used_fraction or 0.0)
        host_available = min(
            (
                item.available_mb
                for item in samples
                if item.source != "cgroup" and item.available_mb is not None
            ),
            default=None,
        )
        if gpu.available:
            return MemorySnapshot(
                source=f"{binding.source}+pynvml",
                total_mb=binding.total_mb,
                used_mb=binding.used_mb,
                gpu_total_mb=gpu.gpu_total_mb,
                gpu_used_mb=gpu.gpu_used_mb,
                host_available_mb=host_available,
                raw=binding.raw,
                sampled_at=max(binding.sampled_at, gpu.sampled_at),
            )
        if host_available is not None:
            return MemorySnapshot(
                source=binding.source,
                total_mb=binding.total_mb,
                used_mb=binding.used_mb,
                host_available_mb=host_available,
                raw=binding.raw,
                sampled_at=binding.sampled_at,
            )
        return binding

    def close(self) -> None:
        for probe in self.system_probes:
            probe.close()
        self.nvml.close()

    def __enter__(self) -> "AutoMemoryProbe":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class HardwareCircuitOpen(RuntimeError):
    def __init__(self, stage: str, reason: str, snapshot: MemorySnapshot) -> None:
        super().__init__(f"hardware circuit open at {stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.snapshot = snapshot


class MemoryGuard:
    def __init__(self, probe: MemoryProbe, config: MemoryConfig) -> None:
        self.probe = probe
        self.config = config

    def check(self, stage: str) -> MemorySnapshot:
        sample = self.probe.snapshot()
        if not sample.available:
            if self.config.monitor_required:
                raise HardwareCircuitOpen(
                    stage,
                    f"memory monitoring unavailable ({sample.error or sample.source})",
                    sample,
                )
            return sample

        reasons: list[str] = []
        if sample.used_fraction is not None and sample.used_fraction >= self.config.max_used_fraction:
            reasons.append(
                f"RAM use {sample.used_fraction:.1%} >= {self.config.max_used_fraction:.1%}"
            )
        absolute_available = sample.host_available_mb
        if absolute_available is None and not sample.source.startswith("cgroup"):
            absolute_available = sample.available_mb
        if absolute_available is not None and absolute_available <= self.config.min_available_mb:
            reasons.append(
                f"available RAM {absolute_available:.0f} MB <= {self.config.min_available_mb:.0f} MB"
            )
        if (
            sample.gpu_used_fraction is not None
            and sample.gpu_used_fraction >= self.config.max_gpu_used_fraction
        ):
            reasons.append(
                f"GPU memory use {sample.gpu_used_fraction:.1%} >= "
                f"{self.config.max_gpu_used_fraction:.1%}"
            )
        if reasons:
            raise HardwareCircuitOpen(stage, "; ".join(reasons), sample)
        return sample


def _unavailable(source: str, reason: str, sampled_at: float) -> MemorySnapshot:
    return MemorySnapshot(
        source=source,
        total_mb=None,
        used_mb=None,
        error=reason,
        sampled_at=sampled_at,
    )
