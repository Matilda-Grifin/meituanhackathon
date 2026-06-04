#!/usr/bin/env python3
import sys
from pathlib import Path

REPO = Path("/root/meituan-lifecare-agent")
BENCH = REPO / "benchmark"
sys.path[:0] = [str(REPO), str(BENCH)]

import os

for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip().replace("\r", "")
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from vitabench_eval.load_tasks import load_task
from vitabench_eval.trajectory_evaluator import evaluate_trajectory, _sliding_windows

task = load_task("T063_033")
traj = [
    {"role": "user", "content": "哈尔滨冰雪大世界半日游，要保暖。"},
    {"role": "assistant", "content": "好的，我帮您规划中央大街附近半日行程。"},
]
windows = _sliding_windows(traj)
criteria = task.get("evaluation_criteria") or {}
rubrics = len((criteria.get("expected_states") or [])) + len(criteria.get("overall_rubrics") or [])
print("windows_small", len(windows), "rubrics_blocks", len(criteria.get("expected_states") or []))

try:
    r = evaluate_trajectory(task, traj, model="judge", temperature=0.1)
    print("judge_ok", r.get("reward"), r.get("rubric_total"))
except Exception as e:
    print("judge_fail", type(e).__name__, str(e)[:1200])
