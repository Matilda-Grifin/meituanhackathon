#!/usr/bin/env python3
import json
from pathlib import Path

p = Path("/root/meituan-lifecare-agent/benchmark/model_selection/results/v63-batch/qwen/batch_progress.json")
data = json.loads(p.read_text(encoding="utf-8"))
for x in data:
    if x.get("ok") is False:
        print(x)
