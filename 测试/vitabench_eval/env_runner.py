"""MCP tool log tracker for 6.3 Orchestrator Env step (OpenClaw adaptation)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _default_log_path() -> Path:
    custom = os.environ.get("LIFECARE_MCP_TOOL_LOG_PATH", "").strip()
    if custom:
        return Path(custom)
    for candidate in (
        Path("/root/meituan-lifecare-agent/benchmark/results/mcp_tool_calls.jsonl"),
        Path.cwd() / "results" / "mcp_tool_calls.jsonl",
        Path.cwd().parent / "results" / "mcp_tool_calls.jsonl",
    ):
        if candidate.parent.is_dir() or candidate.parent.name == "results":
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
    out = Path.cwd() / "results"
    out.mkdir(parents=True, exist_ok=True)
    return out / "mcp_tool_calls.jsonl"


def _log_path() -> Path:
    return _default_log_path()


def logging_enabled() -> bool:
    v = os.environ.get("LIFECARE_MCP_TOOL_LOG", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


class McpLogTracker:
    """Track JSONL offset and drain new MCP invocations after each Agent turn."""

    def __init__(self, log_path: Path | None = None) -> None:
        self.path = log_path or _log_path()
        if not self.path.is_file():
            alt = _default_log_path()
            if alt.is_file():
                self.path = alt
        self.offset = self.path.stat().st_size if self.path.is_file() else 0

    def drain_new_entries(self) -> list[dict]:
        if not logging_enabled() or not self.path.is_file():
            return []
        size = self.path.stat().st_size
        if size <= self.offset:
            return []
        with self.path.open("r", encoding="utf-8") as f:
            f.seek(self.offset)
            chunk = f.read()
        self.offset = size
        entries: list[dict] = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries


def entries_to_tool_messages(entries: list[dict]) -> list[dict]:
    msgs: list[dict] = []
    for e in entries:
        tool = e.get("tool") or "mcp_tool"
        preview = e.get("result_preview") or ""
        if not preview and e.get("error"):
            preview = f"error: {e['error']}"
        if not preview and e.get("ok") is False:
            preview = "tool failed"
        if not preview:
            preview = f"ok={e.get('ok', True)} duration_ms={e.get('duration_ms')}"
        msgs.append({"role": "tool", "name": tool, "content": preview})
    return msgs


def count_mcp_errors(entries: list[dict]) -> int:
    return sum(1 for e in entries if e.get("ok") is False or e.get("error"))
