#!/usr/bin/env python3
"""ECS Harness API 冒烟（避免 shell 转义问题）。"""
from __future__ import annotations

import json
import subprocess
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "root@121.41.81.58"

REMOTE = r"""
python3 <<'PY'
import json, urllib.request
def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:8098{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())
print("health", urllib.request.urlopen("http://127.0.0.1:8098/health").read().decode())
print("user", post("/api/harness/on-user-message", {"session_key": "smoke", "message": "杭州玩"}))
plan = "## 📋 行程速览\n\n| 时段 | 做什么 |\n|---|---|\n| 12:00 | 午餐 |\n\n## 💰 预算参考\n\n| 项目 | 费用 |\n|---|---|\n| 餐饮 | 200 |"
print("repair", post("/api/harness/validate-and-repair", {"session_key": "smoke", "text": plan}))
PY
"""

proc = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, REMOTE], capture_output=True, text=True)
print(proc.stdout)
if proc.stderr:
    print(proc.stderr, file=sys.stderr)
raise SystemExit(proc.returncode)
