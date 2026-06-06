#!/usr/bin/env python3
"""
将 Harness 改动部署到 ECS（先自动备份，再打包同步、安装依赖、重启服务）。

用法（本机）：
  python scripts/ecs_deploy_harness.py
  python scripts/ecs_deploy_harness.py --host root@121.41.81.58 --skip-backup
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOST = "root@121.41.81.58"
REMOTE_REPO = "/root/meituan-lifecare-agent"

# 部署 Harness 必需路径（相对仓库根）
DEPLOY_PATHS = [
    "lifecare/harness",
    "lifecare/__init__.py",
    "run_mcp.py",
    "gateway_context_api.py",
    "requirements.txt",
    "workspace/SOUL.md",
    "workspace/skills/local-itinerary-planner",
    "workspace/skills/travel-intake",
    "测试/harness_eval.py",
    "测试/rubric_engine.py",
    "gateway-chat-ui/src/harnessClient.ts",
    "gateway-chat-ui/src/App.tsx",
    "gateway-chat-ui/scripts/ecs_apply_lifecare_openclaw.py",
    "scripts/ecs_backup_online.py",
    "scripts/ecs_deploy_harness.py",
]

SKIP_DIR_NAMES = {"node_modules", ".venv", "__pycache__", ".git", "dist"}


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def _ssh(host: str, cmd: str) -> None:
    _run(["ssh", "-o", "BatchMode=yes", host, cmd])


def _make_tarball() -> Path:
    tmp = Path(tempfile.gettempdir()) / "lifecare-harness-deploy.tar.gz"
    with tarfile.open(tmp, "w:gz") as tar:
        for rel in DEPLOY_PATHS:
            p = ROOT / rel
            if p.is_file():
                tar.add(p, arcname=rel)
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file() and not any(part in SKIP_DIR_NAMES for part in f.parts):
                        tar.add(f, arcname=str(f.relative_to(ROOT)))
            else:
                print(f"warn: missing {rel}")
    print(f"tarball: {tmp} ({tmp.stat().st_size // 1024} KB)")
    return tmp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--skip-ui-build", action="store_true")
    args = ap.parse_args()

    if not args.skip_backup:
        _run([sys.executable, str(ROOT / "scripts" / "ecs_backup_online.py"), "--host", args.host])

    tarball = _make_tarball()
    remote_tar = "/tmp/lifecare-harness-deploy.tar.gz"
    _run(["scp", "-o", "BatchMode=yes", str(tarball), f"{args.host}:{remote_tar}"])

    remote = f"""
set -e
cd {REMOTE_REPO}
tar -xzf {remote_tar}
python3 -m pip install -q -r requirements.txt
mkdir -p /root/.openclaw/harness_state
python3 gateway-chat-ui/scripts/ecs_apply_lifecare_openclaw.py 2>/dev/null || true
python3 - <<'PY'
import json
from pathlib import Path
cfg_path = Path("/root/.openclaw/openclaw.json")
if cfg_path.is_file():
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    mcp = cfg.setdefault("mcp", {{}}).setdefault("servers", {{}}).setdefault("lifecare", {{}})
    env = mcp.setdefault("env", {{}})
    env["LIFECARE_HARNESS_LOG"] = "1"
    env["LIFECARE_HARNESS_STATE_DIR"] = "/root/.openclaw/harness_state"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("harness env merged")
PY
# gateway_context_api (8098)
if pgrep -f 'uvicorn gateway_context_api' >/dev/null; then
  pkill -f 'uvicorn gateway_context_api' || true
  sleep 1
fi
nohup python3 -m uvicorn gateway_context_api:app --host 127.0.0.1 --port 8098 >/var/log/gateway_context_api.log 2>&1 &
sleep 1
# OpenClaw gateway
pkill -f 'openclaw/dist/index.js gateway' 2>/dev/null || pkill -f openclaw 2>/dev/null || true
sleep 2
nohup openclaw gateway --port 18789 >>/root/openclaw-gateway.log 2>&1 &
sleep 3
python3 lifecare/harness/test_harness.py
echo DEPLOY_OK
rm -f {remote_tar}
"""
    _ssh(args.host, remote)

    if not args.skip_ui_build:
        ui_remote = f"""
set -e
cd {REMOTE_REPO}/gateway-chat-ui
if command -v npm >/dev/null; then
  npm install --silent 2>/dev/null || true
  npm run build
  echo UI_BUILD_OK
else
  echo SKIP_UI_NO_NPM
fi
"""
        _ssh(args.host, ui_remote)

    print("\nDeploy complete.")
    print("Backup: /root/backups/lifecare-online-*.tar.gz on ECS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
