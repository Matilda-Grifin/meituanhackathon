#!/usr/bin/env python3
"""Promote /tmp/T063_033_debug.* into official v63-batch/qwen/."""
import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("/root/meituan-lifecare-agent/benchmark/model_selection/results/v63-batch/qwen")
DEBUG_RUN = Path("/tmp/T063_033_debug.json")
DEBUG_EVAL = Path("/tmp/T063_033_eval_detail.json")
TASK_ID = "T063_033"

if not DEBUG_RUN.is_file():
    raise SystemExit(f"missing {DEBUG_RUN}")

data = json.loads(DEBUG_RUN.read_text(encoding="utf-8"))
run_path = OUT / f"{TASK_ID}_run.json"
run_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote {run_path}")

if DEBUG_EVAL.is_file():
    eval_path = OUT / f"{TASK_ID}_eval_detail.json"
    eval_path.write_text(DEBUG_EVAL.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {eval_path}")
else:
    ri = data.get("reward_info") or {}
    eval_detail = {
        "task_id": TASK_ID,
        "termination": data.get("termination"),
        "reward": ri.get("reward"),
        "rubric_states": ri.get("rubric_states"),
        "first_response": data.get("first_response"),
    }
    eval_path = OUT / f"{TASK_ID}_eval_detail.json"
    eval_path.write_text(json.dumps(eval_detail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {eval_path} (from run)")

reward = (data.get("reward_info") or {}).get("reward")
row = {
    "task_id": TASK_ID,
    "ok": True,
    "termination": data.get("termination"),
    "steps": data.get("steps"),
    "reward": reward,
    "rubric_met": (data.get("reward_info") or {}).get("rubric_met"),
    "rubric_total": (data.get("reward_info") or {}).get("rubric_total"),
    "promoted_from": "/tmp/T063_033_debug.json",
    "promoted_at": datetime.now(timezone.utc).isoformat(),
}

for name in ("batch_progress.json",):
    p = OUT / name
    if p.is_file():
        summary = json.loads(p.read_text(encoding="utf-8"))
        summary = [r for r in summary if r.get("task_id") != TASK_ID] + [row]
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"updated {p}")

summary_path = OUT / "batch_summary.json"
if summary_path.is_file():
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    results = payload.get("results") or []
    results = [r for r in results if r.get("task_id") != TASK_ID] + [row]
    payload["results"] = results
    payload["ok_count"] = sum(1 for r in results if r.get("ok"))
    payload["promoted_033_at"] = row["promoted_at"]
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated {summary_path} ok_count={payload['ok_count']}")

print("done", TASK_ID, "termination=", data.get("termination"), "reward=", reward)
