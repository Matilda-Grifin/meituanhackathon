#!/usr/bin/env python3
"""Deploy gateway_context_api + nginx /api + gateway-chat-ui dist to ECS."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HOST = "root@121.41.81.58"
REPO = Path(__file__).resolve().parents[2]
HACK_ENV = REPO.parent / ".env"
DIST = REPO / "gateway-chat-ui" / "dist"
SETUP = Path(__file__).resolve().parent / "ecs_setup_client_context.sh"


def _read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")

    def g(key: str) -> str:
        m = re.search(rf"^{re.escape(key)}=(.*)$", raw, re.M)
        return (m.group(1).strip() if m else "").strip()

    keys = (
        "AMAP_KEY",
        "ARK_API_KEY",
        "ARK_BASE_URL",
        "ARK_MODEL_NAME",
        "picture_model",
    )
    return {k: g(k) for k in keys if g(k)}


def _build_api_tar() -> Path:
    members = [
        "gateway_context_api.py",
        "requirements.txt",
        "lifecare",
    ]
    fd, path = tempfile.mkstemp(suffix=".tar.gz")
    import os as _os

    _os.close(fd)
    out = Path(path)
    with tarfile.open(out, "w:gz") as tar:
        for m in members:
            tar.add(REPO / m, arcname=m)
    return out


def main() -> None:
    if not DIST.is_dir():
        sys.exit(f"run: cd gateway-chat-ui && npm run build  (missing {DIST})")
    if not SETUP.is_file():
        sys.exit(f"missing {SETUP}")

    secrets = _read_env(HACK_ENV)
    tgz = _build_api_tar()
    try:
        subprocess.check_call(["scp", "-o", "BatchMode=yes", str(tgz), f"{HOST}:/tmp/lifecare-context.tgz"])
        subprocess.check_call(
            ["scp", "-o", "BatchMode=yes", "-r", f"{DIST}/.", f"{HOST}:/var/www/gateway-chat-ui/"],
        )
        subprocess.check_call(["scp", "-o", "BatchMode=yes", str(SETUP), f"{HOST}:/tmp/ecs_setup_client_context.sh"])
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", HOST, "cat > /tmp/lifecare_inject.json"],
            input=json.dumps(secrets, ensure_ascii=False).encode("utf-8"),
            check=True,
        )
        subprocess.check_call(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                HOST,
                "set -e; mkdir -p /root/meituan-lifecare-agent /var/www/gateway-chat-ui; "
                "tar xzf /tmp/lifecare-context.tgz -C /root/meituan-lifecare-agent; "
                "bash /tmp/ecs_setup_client_context.sh",
            ],
        )
        pub = subprocess.check_output(
            ["curl.exe", "-sk", "--max-time", "15", "https://121.41.81.58:8080/api/client-context"],
        )
        print("public /api/client-context:", pub.decode("utf-8", errors="replace")[:600])
    finally:
        tgz.unlink(missing_ok=True)

    print("done")


if __name__ == "__main__":
    main()
