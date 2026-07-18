"""Run repository validation with paid/cloud credentials deliberately disabled."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str]) -> None:
    print(f"[offline] {' '.join(command)}")
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    env = os.environ.copy()
    env.pop("QWEN_API_KEY", None)
    env.pop("DASHSCOPE_API_KEY", None)
    env["CONGLOMERAITE_OFFLINE"] = "1"
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + existing_path if existing_path else ""
    )

    run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        env=env,
    )
    run(
        [sys.executable, "-m", "unittest", "-v", "test_index.py"],
        cwd=ROOT / "cloud" / "alibaba-telemetry",
        env=env,
    )
    run(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "src",
            "tests",
            "cloud/alibaba-telemetry",
        ],
        env=env,
    )
    print("[offline] PASS: no QwenCloud credential was available to child processes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
