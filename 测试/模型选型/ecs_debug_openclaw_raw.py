#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path

cfg = Path("/root/.openclaw/openclaw.json")
token = json.loads(cfg.read_text()).get("gateway", {}).get("auth", {}).get("token", "")
env = os.environ.copy()
if token:
    env["OPENCLAW_GATEWAY_TOKEN"] = token
cmd = [
    "openclaw",
    "agent",
    "--agent",
    "main",
    "-m",
    "今天出发一个人，想看古典园林，先查天气",
    "--json",
    "--session-id",
    "debug-raw-001",
    "--timeout",
    "420",
    "--thinking",
    "medium",
]
proc = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=450,
    cwd="/root/meituan-lifecare-agent",
    env=env,
)
print("rc", proc.returncode)
print("stdout_len", len(proc.stdout))
print("stderr_tail", proc.stderr[-1500:] if proc.stderr else "")
raw = proc.stdout.strip()
print("stdout_head", raw[:500])
print("stdout_tail", raw[-800:] if raw else "")
if "{" in raw:
    doc = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    print("doc_keys", list(doc.keys()))
    print("meta_keys", list((doc.get("meta") or {}).keys())[:30])
