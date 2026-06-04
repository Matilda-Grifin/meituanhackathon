#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path

p = Path("/root/meituan-lifecare-agent/benchmark/model_selection/results/v63-batch/qwen/batch_progress.json")
data = json.loads(p.read_text(encoding="utf-8"))
ok = [x for x in data if x.get("ok")]
fail = [x for x in data if not x.get("ok")]
term = Counter(x.get("termination") for x in ok)
print("progress:", len(data), "ok:", len(ok), "fail:", len(fail))
print("terminations:", dict(term))
if fail:
    print("failed_ids:", [x["task_id"] for x in fail])
for x in ok[-5:]:
    print("recent_ok:", x.get("task_id"), x.get("termination"), x.get("reward"))
