#!/usr/bin/env python3
"""
备份线上 OpenClaw + 本项目关键文件，便于 Harness 等改动后回滚。

用法（本机，需 SSH 到 ECS）：
  python scripts/ecs_backup_online.py
  python scripts/ecs_backup_online.py --host root@121.41.81.58

备份落在服务器：
  /root/backups/lifecare-online-YYYYMMDD-HHMMSS.tar.gz
  /root/backups/lifecare-online-YYYYMMDD-HHMMSS/manifest.json

回滚示例见 docs/线上Agent-Harness约束方案.md 或备份目录内 RESTORE.md。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

DEFAULT_HOST = "root@121.41.81.58"

# 线上关键路径（与 README / ecs_apply_lifecare_openclaw.py 一致）
ONLINE_PATHS = [
    "/root/meituan-lifecare-agent",
    "/root/.openclaw/openclaw.json",
    "/root/.openclaw/workspace",
    "/root/.openclaw/agents/main/sessions",
]

RESTORE_MD = """# 回滚说明

## 解压备份
```bash
cd /root/backups
tar -xzf lifecare-online-*.tar.gz -C /tmp/restore-check
ls /tmp/restore-check
```

## 恢复（在 ECS 上执行，先停网关）
```bash
systemctl stop openclaw-gateway 2>/dev/null || pkill -f openclaw || true

# 恢复仓库（保留当前为 .broken 备查）
mv /root/meituan-lifecare-agent /root/meituan-lifecare-agent.broken-$(date +%s) 2>/dev/null || true
cp -a RESTORE_ROOT/meituan-lifecare-agent /root/

# 恢复 openclaw 配置与 workspace
cp -a RESTORE_ROOT/openclaw.json /root/.openclaw/openclaw.json
rm -rf /root/.openclaw/workspace
cp -a RESTORE_ROOT/workspace /root/.openclaw/workspace

# 可选：恢复 sessions
cp -a RESTORE_ROOT/sessions /root/.openclaw/agents/main/sessions

cd /root/meituan-lifecare-agent
python3 gateway-chat-ui/scripts/ecs_apply_lifecare_openclaw.py
systemctl start openclaw-gateway 2>/dev/null || true
```

将 `RESTORE_ROOT` 替换为解压后的目录名。
"""


def _ssh(host: str, cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup online lifecare files on ECS")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = f"/root/backups/lifecare-online-{stamp}"
    archive = f"{backup_dir}.tar.gz"

    remote_script = f"""
set -e
mkdir -p /root/backups
BK="{backup_dir}"
mkdir -p "$BK"
for p in {' '.join(ONLINE_PATHS)}; do
  if [ -e "$p" ]; then
    dest="$BK$(dirname "$p")"
    mkdir -p "$dest"
    cp -a "$p" "$dest/"
    echo "backed: $p"
  else
    echo "skip(missing): $p"
  fi
done
cat > "$BK/manifest.json" <<'MANIFEST'
{json.dumps({"created_utc": stamp, "paths": ONLINE_PATHS, "host": args.host}, ensure_ascii=False, indent=2)}
MANIFEST
cat > "$BK/RESTORE.md" <<'RESTORE'
{RESTORE_MD.replace("RESTORE_ROOT", backup_dir)}
RESTORE
tar -czf "{archive}" -C /root/backups "$(basename "$BK")"
echo "ARCHIVE={archive}"
ls -lh "{archive}"
"""

    if args.dry_run:
        print(remote_script)
        return 0

    print(f"Connecting {args.host} …")
    proc = _ssh(args.host, remote_script, timeout=600)
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr or "ssh failed", file=sys.stderr)
        return proc.returncode

    print(f"\nBackup OK: {archive}")
    print("Manifest lists:", ", ".join(ONLINE_PATHS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
