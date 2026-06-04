#!/usr/bin/env python3
"""ECS 冒烟：API 生图 + OpenClaw 一轮完整方案（可选第二句补槽）。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

HOST = "root@121.41.81.58"
BASE = "https://121.41.81.58:8080"
ROOT = Path(__file__).resolve().parents[2]
SAMPLE = (
    ROOT.parent
    / "待修复"
    / "模型选型评测"
    / "6.3方案"
    / "qwen方案类输出样例.md"
)


def curl_json(url: str, *, data: dict | None = None, timeout: int = 120) -> dict:
    cmd = ["curl.exe", "-sk", "--max-time", str(timeout), url]
    if data is not None:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json", "-d", json.dumps(data, ensure_ascii=False)]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    return json.loads(out)


def load_plan_text() -> str:
    raw = SAMPLE.read_text(encoding="utf-8")
    m = re.search(r"(^# 🗺️.*)", raw, re.MULTILINE | re.DOTALL)
    if not m:
        sys.exit("sample plan not found")
    return m.group(1).strip()


def test_api_image() -> None:
    print("=== [1] POST /api/itinerary-image (sample plan) ===")
    plan = load_plan_text()
    job_id = f"smoke-{uuid.uuid4().hex[:12]}"
    doc = curl_json(f"{BASE}/api/itinerary-image", data={"plan_markdown": plan, "job_id": job_id}, timeout=180)
    print(json.dumps({k: doc.get(k) for k in ("ok", "cancelled", "image_url", "timing_ms")}, ensure_ascii=False, indent=2))
    if not doc.get("ok"):
        sys.exit("itinerary-image API failed")
    print("image ok:", str(doc.get("image_url", ""))[:80], "...")


def ssh_agent(messages: list[str], session_id: str) -> str:
    repo = "/root/meituan-lifecare-agent"
    last_text = ""
    for i, msg in enumerate(messages):
        esc = msg.replace("'", "'\\''")
        cmd = (
            f"cd {repo} && openclaw agent --agent main -m '{esc}' --json "
            f"--session-id {session_id} --timeout 420 2>/dev/null"
        )
        print(f"\n=== [2.{i+1}] openclaw agent turn {i+1} ===")
        print("user:", textwrap.shorten(msg, 120))
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", HOST, cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=480,
        )
        raw = proc.stdout.strip()
        if proc.returncode != 0 and not raw:
            print(proc.stderr[-1500:])
            sys.exit(f"agent turn {i+1} failed rc={proc.returncode}")
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0:
            print(raw[:500])
            sys.exit("no json from agent")
        doc = json.loads(raw[start : end + 1])
        result = doc.get("result") if isinstance(doc.get("result"), dict) else doc
        meta = result.get("meta") or doc.get("meta") or {}
        last_text = (
            meta.get("finalAssistantVisibleText")
            or meta.get("finalAssistantRawText")
            or ""
        )
        print("assistant chars:", len(last_text))
        print("head:", textwrap.shorten(last_text.replace("\n", " "), 200))
    return last_text


def test_agent_plan() -> None:
    sid = f"smoke-img-{uuid.uuid4().hex[:8]}"
    text = ssh_agent(
        [
            "我在杭州西湖附近，带6岁孩子想玩半天，帮我规划可执行的出行方案",
            "全部用默认",
        ],
        sid,
    )
    has_table = "行程速览" in text or "## 📋" in text
    has_budget = "预算" in text
    print("\n=== plan check ===")
    print("has overview table:", has_table)
    print("has budget:", has_budget)
    if not (has_table and len(text) > 800):
        sys.exit("agent did not return full plan")
    print("agent long plan: OK")


def main() -> None:
    test_api_image()
    test_agent_plan()
    print("\nALL SMOKE OK")


if __name__ == "__main__":
    main()
