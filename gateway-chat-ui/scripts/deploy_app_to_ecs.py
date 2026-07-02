#!/usr/bin/env python3
"""Deploy App shell (dist-app → :8081) + backend API updates. Does NOT touch :8080 dist."""
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
DIST_APP = REPO / "gateway-chat-ui" / "dist-app"
UI = REPO / "gateway-chat-ui"
SETUP = UI / "scripts" / "ecs_setup_client_context.sh"
NGINX_APP = UI / "scripts" / "nginx-app-8081-https.conf"


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
    members = ["gateway_context_api.py", "requirements.txt", "lifecare", "run_mcp.py"]
    fd, path = tempfile.mkstemp(suffix=".tar.gz")
    import os as _os

    _os.close(fd)
    out = Path(path)
    with tarfile.open(out, "w:gz") as tar:
        for m in members:
            p = REPO / m
            if p.is_file() or p.is_dir():
                tar.add(p, arcname=m)
    return out


def _ssh(cmd: str) -> None:
    subprocess.check_call(["ssh", "-o", "BatchMode=yes", HOST, cmd])


# App 8081 与 8080 不同源，Gateway 握手会校验 Origin 白名单
_GATEWAY_ORIGIN_PATCH = r"""
python3 << 'PY'
import json
p = "/root/.openclaw/openclaw.json"
with open(p, encoding="utf-8") as f:
    cfg = json.load(f)
origins = cfg.setdefault("gateway", {}).setdefault("controlUi", {}).setdefault("allowedOrigins", [])
need = "https://121.41.81.58:8081"
changed = False
if need not in origins:
    origins.append(need)
    changed = True
if changed:
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print("gateway allowedOrigins: added", need)
    import subprocess
    subprocess.run(["openclaw", "gateway", "restart"], check=False)
else:
    print("gateway allowedOrigins: ok")
PY
"""


def main() -> None:
    if not DIST_APP.is_dir():
        sys.exit(f"run: cd gateway-chat-ui && npm run build:app  (missing {DIST_APP})")
    if not SETUP.is_file():
        sys.exit(f"missing {SETUP}")
    if not NGINX_APP.is_file():
        sys.exit(f"missing {NGINX_APP}")

    secrets = _read_env(HACK_ENV)
    tgz = _build_api_tar()
    try:
        _ssh("mkdir -p /var/www/gateway-chat-ui-app /root/meituan-lifecare-agent")
        subprocess.check_call(["scp", "-o", "BatchMode=yes", str(tgz), f"{HOST}:/tmp/lifecare-context.tgz"])
        subprocess.check_call(
            ["scp", "-o", "BatchMode=yes", "-r", f"{DIST_APP}/.", f"{HOST}:/var/www/gateway-chat-ui-app/"],
        )
        subprocess.check_call(["scp", "-o", "BatchMode=yes", str(SETUP), f"{HOST}:/tmp/ecs_setup_client_context.sh"])
        subprocess.check_call(["scp", "-o", "BatchMode=yes", str(NGINX_APP), f"{HOST}:/tmp/nginx-app-8081.conf"])
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", HOST, "cat > /tmp/lifecare_inject.json"],
            input=json.dumps(secrets, ensure_ascii=False).encode("utf-8"),
            check=True,
        )
        _ssh(
            "set -e; "
            "mkdir -p /root/meituan-lifecare-agent /var/www/gateway-chat-ui-app; "
            "tar xzf /tmp/lifecare-context.tgz -C /root/meituan-lifecare-agent; "
            "sed -i 's/\\r$//' /tmp/ecs_setup_client_context.sh; "
            "bash /tmp/ecs_setup_client_context.sh; "
            "cp /tmp/nginx-app-8081.conf /etc/nginx/conf.d/gateway-chat-ui-app-8081.conf; "
            "nginx -t && systemctl reload nginx; "
            + _GATEWAY_ORIGIN_PATCH.strip()
        )
    finally:
        tgz.unlink(missing_ok=True)

    checks = [
        ("https://121.41.81.58:8081/", "app root"),
        ("https://121.41.81.58:8081/api/client-context", "app /api"),
        ("https://121.41.81.58:8081/api/session-pois?session_key=test", "session-pois"),
        ("https://121.41.81.58:8080/", "desktop unchanged"),
    ]
    for url, label in checks:
        try:
            out = subprocess.check_output(
                ["curl.exe", "-sk", "--max-time", "20", "-o", "-", "-w", "\nHTTP:%{http_code}", url],
                stderr=subprocess.STDOUT,
            )
            print(f"{label}: {out.decode('utf-8', errors='replace')[:400]}")
        except subprocess.CalledProcessError as e:
            print(f"{label}: FAIL {e}")

    print("\nApp URL: https://121.41.81.58:8081/")
    print("done")


if __name__ == "__main__":
    main()
