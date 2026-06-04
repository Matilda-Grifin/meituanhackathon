#!/usr/bin/env python3
"""Smoke-test lifecare MCP stdio server (tools/list)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path("/root/meituan-lifecare-agent")


def main() -> None:
    proc = subprocess.Popen(
        [sys.executable, "run_mcp.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
        env=os.environ.copy(),
    )
    assert proc.stdin and proc.stdout

    def send(msg: dict) -> str:
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()
        return proc.stdout.readline().decode()

    init = send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        }
    )
    print("initialize:", init[:120])
    tools = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    data = json.loads(tools)
    names = [t.get("name") for t in data.get("result", {}).get("tools", [])]
    print("tools:", names)
    if not any(n and "weather" in n for n in names):
        raise SystemExit("lifecare_get_weather not in tools/list")
    proc.terminate()
    print("OK")


if __name__ == "__main__":
    main()
