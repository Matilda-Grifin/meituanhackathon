#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

REPO = Path("/root/meituan-lifecare-agent")
BENCH = REPO / "benchmark"
task_id = sys.argv[1] if len(sys.argv) > 1 else "T063_023"
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip().replace("\r", "")
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
env = {**os.environ, "PYTHONPATH": f"{REPO}:{BENCH}"}
cmd = [
    sys.executable,
    str(BENCH / "vitabench_eval/run_benchmark.py"),
    "--task-id",
    task_id,
    "--agent-timeout-s",
    "420",
    "--out",
    f"/tmp/{task_id}_cap.json",
]
p = subprocess.run(cmd, cwd=str(BENCH), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
print("rc", p.returncode)
print("=== stderr ===")
print(p.stderr[-2500:] if p.stderr else "(empty)")
print("=== stdout tail ===")
print(p.stdout[-800:] if p.stdout else "(empty)")
