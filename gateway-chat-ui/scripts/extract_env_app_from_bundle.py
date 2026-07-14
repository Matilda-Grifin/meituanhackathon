#!/usr/bin/env python3
"""Extract inlined Vite env defaults from known-good 8081 bundle into .env.app (on server)."""
from __future__ import annotations

import re
from pathlib import Path

t = Path("/var/www/gateway-chat-ui-app/assets/app-Cq21YTdI.js.bak-logo").read_text(
    encoding="utf-8", errors="ignore"
)

# Heuristics used by App.tsx / previous builds
ws = re.findall(r"wss?://[0-9A-Za-z.:/_-]+", t)
token_like = re.findall(r'"([A-Za-z0-9_-]{20,})"', t)
session = re.findall(r"agent:[a-z0-9:_-]+", t)

# Prefer public IP wss if present
ws_prefer = [u for u in ws if "121.41" in u or "18789" in u]
ws_val = (ws_prefer or ws or [""])[0]

# Amap key often looks like alphanumeric 32
amap = ""
for m in re.findall(r'"([a-f0-9]{32})"', t, flags=re.I):
    amap = m
    break

# Gateway token: hard to detect; leave empty if unsure — app may use /api
# Look near "gateway" strings
tok = ""
for pat in [
    r'gatewayToken[=:]\"([^\"]+)\"',
    r'token:\"([^\"]{16,})\"',
    r'VITE_GATEWAY_TOKEN\",\"([^\"]+)\"',
]:
    m = re.search(pat, t)
    if m:
        tok = m.group(1)
        break

out = Path("/tmp/gateway-chat-ui-build/.env.app")
out.parent.mkdir(parents=True, exist_ok=True)

# Always force mobile shell for app build
lines = [
    "VITE_APP_SHELL=mobile",
    "VITE_AUTO_CONNECT=true",
    "VITE_COMPACT_UI=true",
    "VITE_SHOW_DEBUG=false",
]
if ws_val:
    lines.append(f"VITE_DEFAULT_GATEWAY_WS={ws_val}")
if session:
    lines.append(f"VITE_DEFAULT_SESSION_KEY={session[0]}")
if tok:
    lines.append(f"VITE_GATEWAY_TOKEN={tok}")
if amap:
    lines.append(f"VITE_AMAP_JS_KEY={amap}")

out.write_text("\n".join(lines) + "\n", encoding="utf-8")
# print keys only
print("wrote", out)
for line in lines:
    k = line.split("=", 1)[0]
    v = line.split("=", 1)[1] if "=" in line else ""
    print(k, "len", len(v), "preview", (v[:12] + "…") if len(v) > 12 else v)
