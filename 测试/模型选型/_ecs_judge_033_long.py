#!/usr/bin/env python3
"""Judge T063_033 with a long synthetic trajectory (like post-agent run)."""
import json
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
# reuse a successful long trajectory from another task as size proxy
proxy = BENCH / "model_selection/results/v63-batch/qwen/T063_030_run.json"
if proxy.is_file():
    traj = json.loads(proxy.read_text(encoding="utf-8")).get("trajectory") or []
    print("proxy_traj_messages", len(traj), "from", proxy.name)
else:
    traj = []
    for i in range(8):
        traj.append({"role": "user", "content": f"用户消息{i}" * 50})
        traj.append({"role": "assistant", "content": f"助手回复{i}" * 200, "tool_calls": [{"name": "amap_search", "args": {}}]})
        traj.append({"role": "tool", "name": "amap_search", "content": json.dumps({"pois": [{"name": "冰雪馆"}] * 5}, ensure_ascii=False) * 3})
    print("synthetic_traj_messages", len(traj))

wins = _sliding_windows(traj)
print("windows", len(wins), "first_window_chars", len(wins[0][0].get("content", "")) if wins else 0)

try:
    r = evaluate_trajectory(task, traj, model="judge", temperature=0.1)
    print("OK reward", r.get("reward"), "windows_done", r.get("windows"))
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:1500])
