#!/usr/bin/env python3
"""SCP ecs_switch_volcengine_ark.py to ECS and run it with ARK_* from repo-root .env (not committed)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# gateway-chat-ui/scripts -> parents[3] = meituan hackathon/ (.env)
ROOT = Path(__file__).resolve().parents[3]
ENV = ROOT / ".env"
SCRIPT = Path(__file__).resolve().parent / "ecs_switch_volcengine_ark.py"
HOST = "root@121.41.81.58"
REMOTE = "/tmp/ecs_switch_volcengine_ark.py"


def _get(key: str, raw: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.*)$", raw, re.M)
    return (m.group(1).strip() if m else "").strip()


def main() -> None:
    if not ENV.is_file():
        print(f"missing {ENV}", file=sys.stderr)
        sys.exit(1)
    raw = ENV.read_text(encoding="utf-8")
    key = _get("ARK_API_KEY", raw)
    if not key:
        print("ARK_API_KEY empty in .env", file=sys.stderr)
        sys.exit(1)
    base = _get("ARK_BASE_URL", raw) or "https://ark.cn-beijing.volces.com/api/v3"
    model = _get("ARK_MODEL_NAME", raw) or "doubao-seed-2-0-mini-260428"

    subprocess.check_call(
        ["scp", "-o", "BatchMode=yes", str(SCRIPT), f"{HOST}:{REMOTE}"],
    )
    remote_cmd = (
        f"ARK_API_KEY={key!r} ARK_BASE_URL={base!r} ARK_MODEL_NAME={model!r} "
        f"python3 {REMOTE} --restart-gateway"
    )
    subprocess.check_call(["ssh", "-o", "BatchMode=yes", HOST, remote_cmd])


if __name__ == "__main__":
    main()
