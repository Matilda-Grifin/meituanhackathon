#!/usr/bin/env python3
"""Build gateway-chat-ui App shell on ECS and deploy static only to :8081."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

KEY = Path(__file__).resolve().parents[2] / "新密钥.pem"
HOST = "root@121.41.81.58"
LOCAL_UI = Path(__file__).resolve().parents[1]
REMOTE_BUILD = "/tmp/gateway-chat-ui-build"
WWW = "/var/www/gateway-chat-ui-app"

SSH = ["ssh", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", HOST]
SCP = ["scp", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no"]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd[:8]), "..." if len(cmd) > 8 else "")
    subprocess.check_call(cmd)


def main() -> None:
    if not KEY.is_file():
        sys.exit(f"missing key: {KEY}")

    tarball = Path("/tmp/gateway-chat-ui-src.tgz")
    # Pack sources needed to build App
    files = [
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "tsconfig.app.json",
        "tsconfig.node.json",
        "vite.config.ts",
        "vite.app.config.ts",
        "index.html",
        "app.html",
        "eslint.config.js",
        ".env.app",  # compact/auto-connect；若缺则靠 vite.app.config 默认值
        "src",
        "public",
        "patches",
    ]
    existing = [f for f in files if (LOCAL_UI / f).exists()]
    subprocess.check_call(
        ["tar", "czf", str(tarball), "-C", str(LOCAL_UI), *existing],
    )

    run(SSH + [f"rm -rf {REMOTE_BUILD} && mkdir -p {REMOTE_BUILD}"])
    run(SCP + [str(tarball), f"{HOST}:/tmp/gateway-chat-ui-src.tgz"])
    run(
        SSH
        + [
            "set -e; "
            f"tar xzf /tmp/gateway-chat-ui-src.tgz -C {REMOTE_BUILD}; "
            f"cd {REMOTE_BUILD}; "
            "python3 -c \""
            "from pathlib import Path\n"
            "p=Path('.env.app')\n"
            "t=p.read_text() if p.exists() else ''\n"
            "if 'VITE_AMAP_JS_KEY=' not in t or not any(l.startswith('VITE_AMAP_JS_KEY=') and len(l.split('=',1)[1].strip())>0 for l in t.splitlines()):\n"
            " k=''\n"
            " for f in [Path('/root/.amap_js_key_for_app'), Path('/root/meituan-lifecare-agent/.env')]:\n"
            "  if not f.exists(): continue\n"
            "  raw=f.read_text(errors='ignore')\n"
            "  if f.name.endswith('.env'):\n"
            "   for line in raw.splitlines():\n"
            "    if line.startswith('AMAP_KEY='):\n"
            "     k=line.split('=',1)[1].strip().strip(chr(34)+chr(39)); break\n"
            "  else: k=raw.strip()\n"
            "  if k: break\n"
            " if k:\n"
            "  with p.open('a') as out: out.write('\\nVITE_AMAP_JS_KEY='+k+'\\n')\n"
            "  print('injected_amap_js_key', len(k))\n"
            " else: print('WARN_missing_amap_js_key')\n"
            "else: print('amap_js_key_already_set')\n"
            "\"; "
            "npm install --no-fund --no-audit; "
            "npm run build:app; "
            f"mkdir -p {WWW}; "
            # Replace tree so stale hashed assets do not break smoke checks
            f"find {WWW} -mindepth 1 -maxdepth 1 ! -name 'xiaoxing-logo.jpg' ! -name 'favicon.jpg' -exec rm -rf {{}} +; "
            f"cp -a dist-app/. {WWW}/; "
            f"test -f {WWW}/xiaoxing-logo.jpg || cp -a public/xiaoxing-logo.jpg {WWW}/; "
            f"test -f {WWW}/app.html; "
            f"test -n \"$(ls {WWW}/assets/app-*.js 2>/dev/null)\"; "
            f"grep -q 'touch-action:pan-y' {WWW}/assets/app-*.css; "
            # 确认 App 壳已打进 compact，不会再露出 Gateway 调试面板文案（死代码可仍在 JS 里）
            f"grep -q 'VITE_COMPACT_UI:`true`\\|VITE_COMPACT_UI:\"true\"' {WWW}/assets/app-*.js; "
            f"curl -sk -o /dev/null -w '8081:%{{http_code}}\\n' https://127.0.0.1:8081/; "
            f"ls -lt {WWW}/assets/app-*.js | head -2; "
            f"head -20 {WWW}/app.html"
        ]
    )
    tarball.unlink(missing_ok=True)
    print("deployed app shell (compact + scroll) to :8081")


if __name__ == "__main__":
    main()
