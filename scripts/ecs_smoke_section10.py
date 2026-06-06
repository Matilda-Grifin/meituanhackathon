#!/usr/bin/env python3
"""ECS §10 Harness 冒烟（stage / checklist / POI）。"""
from __future__ import annotations

import json
import subprocess
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "root@121.41.81.58"

REMOTE = r"""
cd /root/meituan-lifecare-agent
python3 <<'PY'
import json, sys, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))

sid = uuid.uuid4().hex[:8]

def post(path, body):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:8098{path}",
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

assert urllib.request.urlopen("http://127.0.0.1:8098/health", timeout=5).status == 200

w = post("/api/harness/on-user-message", {"session_key": f"s10-w-{sid}", "message": "杭州明天冷吗"})
assert w.get("stage") == "light_weather", w

p = post("/api/harness/on-user-message", {"session_key": f"s10-p-{sid}", "message": "帮我规划杭州半日游"})
assert p.get("stage") in ("intake", "planning"), p

post("/api/harness/on-user-message", {"session_key": f"s10-p-{sid}", "message": "选择题答案：第1题选A"})
plan = (
    "## 📋 行程速览\n\n| 时段 | 做什么 | 交通 |\n|---|---|---|\n"
    "| 12:00 | 文和友 | 打车约 3km / 10分钟 |\n\n"
    "## 💰 预算参考\n\n| 项目 | 费用 |\n|---|---|\n| 餐饮 | 200 |"
)
# inject fake search result into state via record (simulate)
from lifecare.harness.session_state import record_tool_call
record_tool_call(
    f"s10-p-{sid}",
    "lifecare_search_places",
    {"keywords": "湘菜", "city": "杭州"},
    json.dumps(
        {
            "ok": True,
            "pois": [
                {
                    "id": "B001",
                    "name": "火宫殿(坡子街总店)",
                    "amap_place_url": "https://www.amap.com/place/B001",
                }
            ],
        },
        ensure_ascii=False,
    ),
)
r = post("/api/harness/validate-and-repair", {"session_key": f"s10-p-{sid}", "text": plan})
assert r.get("ok"), r
text = r.get("text") or ""
assert "预算" in text or "budget_estimate_notice" in (r.get("repairs_applied") or [])
print("SECTION10_SMOKE_OK", w.get("stage"), p.get("stage"), r.get("repairs_applied"))
PY
"""

proc = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, REMOTE], capture_output=True, text=True, encoding="utf-8")
print(proc.stdout)
if proc.stderr:
    print(proc.stderr, file=sys.stderr)
raise SystemExit(proc.returncode)
