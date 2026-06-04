#!/usr/bin/env python3
"""
Pack minimal meituan-lifecare-agent (workspace + run_mcp + lifecare), upload to ECS,
inject AMAP / sandbox URL from hackathon .env, run ecs_apply_lifecare_openclaw.py on the server.

Usage (PowerShell):
  cd "D:\\projects\\meituan hackathon\\meituan-lifecare-agent\\gateway-chat-ui\\scripts"
  python push_lifecare_openclaw_to_ecs.py

Requires: scp/ssh in PATH, key-based auth to root@121.41.81.58 (edit HOST if needed).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HOST = "root@121.41.81.58"
# meituan-lifecare-agent repo root (parent of gateway-chat-ui)
REPO = Path(__file__).resolve().parents[2]
HACK_ENV = REPO.parent / ".env"
SCRIPT_DIR = Path(__file__).resolve().parent
APPLY = SCRIPT_DIR / "ecs_apply_lifecare_openclaw.py"


def _read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")

    def g(key: str) -> str:
        m = re.search(rf"^{re.escape(key)}=(.*)$", raw, re.M)
        return (m.group(1).strip() if m else "").strip()

    return {
        "AMAP_KEY": g("AMAP_KEY"),
        "MOCK_SANDBOX_BASE_URL": g("MOCK_SANDBOX_BASE_URL") or "http://127.0.0.1:9000",
    }


def _build_tar() -> Path:
    members = ["run_mcp.py", "requirements.txt", "workspace", "lifecare"]
    for m in members:
        if not (REPO / m).exists():
            raise SystemExit(f"missing {REPO / m}")
    fd, path = tempfile.mkstemp(suffix=".tar.gz")
    import os as _os

    _os.close(fd)
    out = Path(path)
    with tarfile.open(out, "w:gz") as tar:
        for m in members:
            tar.add(REPO / m, arcname=m)
    return out


def main() -> None:
    if not APPLY.is_file():
        raise SystemExit(f"missing {APPLY}")
    secrets = _read_env(HACK_ENV)
    if not secrets.get("AMAP_KEY"):
        print("WARN: AMAP_KEY empty in hackathon .env — inject file will omit it", file=sys.stderr)

    tgz = _build_tar()
    try:
        subprocess.check_call(["scp", "-o", "BatchMode=yes", str(tgz), f"{HOST}:/tmp/lifecare-mcp.tgz"])
        subprocess.check_call(["scp", "-o", "BatchMode=yes", str(APPLY), f"{HOST}:/tmp/ecs_apply_lifecare_openclaw.py"])
        inj = json.dumps(secrets, ensure_ascii=False)
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", HOST, "cat > /tmp/lifecare_inject.json"],
            input=inj.encode("utf-8"),
            check=True,
        )
        remote = (
            "set -e; mkdir -p /root/meituan-lifecare-agent; "
            "tar xzf /tmp/lifecare-mcp.tgz -C /root/meituan-lifecare-agent; "
            "python3 /tmp/ecs_apply_lifecare_openclaw.py"
        )
        subprocess.check_call(["ssh", "-o", "BatchMode=yes", HOST, remote])
    finally:
        tgz.unlink(missing_ok=True)

    print("done: workspace + lifecare MCP on ECS; gateway restarted")


if __name__ == "__main__":
    main()
