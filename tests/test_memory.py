import tempfile
from pathlib import Path
import unittest

from conglomeraite.config import MemoryConfig
from conglomeraite.memory import (
    CgroupMemoryProbe,
    HardwareCircuitOpen,
    MemoryGuard,
    MemorySnapshot,
    ProcMeminfoProbe,
    TegrastatsProbe,
)


class StaticProbe:
    def __init__(self, sample: MemorySnapshot) -> None:
        self.sample = sample

    def snapshot(self) -> MemorySnapshot:
        return self.sample

    def close(self) -> None:
        pass


class MemoryTests(unittest.TestCase):
    def test_parses_tegrastats_unified_ram(self) -> None:
        sample = TegrastatsProbe.parse(
            "RAM 7168/7764MB (lfb 3x4MB) SWAP 100/8192MB GR3D_FREQ 80%"
        )
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample.used_mb, 7168)
        self.assertEqual(sample.total_mb, 7764)

    def test_proc_memavailable_drives_used_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meminfo"
            path.write_text("MemTotal: 8192000 kB\nMemFree: 100000 kB\nMemAvailable: 2048000 kB\n")
            sample = ProcMeminfoProbe(path).snapshot()
        self.assertEqual(sample.total_mb, 8000)
        self.assertEqual(sample.used_mb, 6000)

    def test_reads_finite_cgroup_v2_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.current").write_text(str(700 * 1024 * 1024))
            (root / "memory.max").write_text(str(1024 * 1024 * 1024))
            sample = CgroupMemoryProbe(root).snapshot()
        self.assertEqual(sample.total_mb, 1024)
        self.assertEqual(sample.used_mb, 700)

    def test_resolves_process_cgroup_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / "system.slice" / "conglomeraite.service"
            service.mkdir(parents=True)
            (service / "memory.current").write_text(str(512 * 1024 * 1024))
            (service / "memory.max").write_text(str(2048 * 1024 * 1024))
            proc = root / "self.cgroup"
            proc.write_text("0::/system.slice/conglomeraite.service\n")
            sample = CgroupMemoryProbe(root, proc).snapshot()
        self.assertEqual(sample.total_mb, 2048)
        self.assertEqual(sample.used_mb, 512)

    def test_guard_trips_before_oom(self) -> None:
        probe = StaticProbe(MemorySnapshot("test", 8000, 7300))
        guard = MemoryGuard(
            probe,
            MemoryConfig(max_used_fraction=0.88, min_available_mb=768),
        )
        with self.assertRaises(HardwareCircuitOpen) as caught:
            guard.check("generator.before")
        self.assertIn("RAM use", caught.exception.reason)
        self.assertIn("available RAM", caught.exception.reason)

    def test_required_monitor_fails_closed(self) -> None:
        probe = StaticProbe(MemorySnapshot("none", None, None, error="missing"))
        guard = MemoryGuard(probe, MemoryConfig(monitor_required=True))
        with self.assertRaises(HardwareCircuitOpen):
            guard.check("critic.before")

    def test_cgroup_uses_fraction_not_host_headroom_floor(self) -> None:
        # The orchestrator's 640 MB systemd limit is smaller than the host's
        # configured 768 MB reserve; only the cgroup fraction applies to it.
        probe = StaticProbe(MemorySnapshot("cgroup", 640, 100))
        guard = MemoryGuard(probe, MemoryConfig(min_available_mb=768))
        self.assertEqual(guard.check("generator.before").source, "cgroup")


if __name__ == "__main__":
    unittest.main()
