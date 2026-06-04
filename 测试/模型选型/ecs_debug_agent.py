#!/usr/bin/env python3
import os
import sys
from pathlib import Path

bench = Path("/root/meituan-lifecare-agent/benchmark")
sys.path[:0] = [str(bench), "/root/meituan-lifecare-agent"]
os.environ.setdefault("LIFECARE_MCP_TOOL_LOG", "1")
os.environ.setdefault(
    "LIFECARE_MCP_TOOL_LOG_PATH",
    str(bench / "results" / "mcp_tool_calls.jsonl"),
)

from vitabench_eval.llm_client import load_repo_env  # noqa: E402
from vitabench_eval.agent_bridge import run_agent_turn  # noqa: E402

load_repo_env()
msg = "今天出发一个人，想看古典园林，苏式面也安排一顿。先查天气"
r = run_agent_turn(msg, session_id="debug-t063-007b", timeout_s=420)
print("error:", r.get("error"))
print("text_len:", len(r.get("assistant_text") or ""))
print("tools:", r.get("tools"))
print("meta_keys:", sorted((r.get("raw_meta") or {}).keys()))
print("meta:", {k: (r.get("raw_meta") or {}).get(k) for k in ("isError", "error", "status", "finalAssistantVisibleText", "toolSummary")})
print("head:", (r.get("assistant_text") or "")[:300])
