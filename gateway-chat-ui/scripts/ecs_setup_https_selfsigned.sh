#!/bin/bash
# 公网 IP：443 + 8080 均 HTTPS，/ws/ 反代 OpenClaw 18789
# 用法：bash ecs_setup_https_selfsigned.sh [公网IP]
set -euo pipefail

PUBLIC_IP="${1:-121.41.81.58}"
SSL_DIR=/etc/nginx/ssl
CONF=/etc/nginx/sites-available/gateway-chat-ui-https
ENABLED=/etc/nginx/sites-enabled/gateway-chat-ui

mkdir -p "$SSL_DIR"

if [ ! -f "$SSL_DIR/gateway-chat.crt" ]; then
  openssl req -x509 -nodes -days 825 \
    -newkey rsa:2048 \
    -keyout "$SSL_DIR/gateway-chat.key" \
    -out "$SSL_DIR/gateway-chat.crt" \
    -subj "/CN=${PUBLIC_IP}" \
    -addext "subjectAltName=IP:${PUBLIC_IP},DNS:localhost" 2>/dev/null || \
  openssl req -x509 -nodes -days 825 \
    -newkey rsa:2048 \
    -keyout "$SSL_DIR/gateway-chat.key" \
    -out "$SSL_DIR/gateway-chat.crt" \
    -subj "/CN=${PUBLIC_IP}"
  echo "created self-signed cert in $SSL_DIR"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/nginx-gateway-chat-ui-https.conf" "$CONF"

rm -f /etc/nginx/sites-enabled/gateway-chat-ui-https
ln -sf "$CONF" "$ENABLED"

export PUBLIC_IP
python3 << PY
import json, os
from pathlib import Path
public_ip = os.environ.get("PUBLIC_IP", "121.41.81.58")
p = Path("/root/.openclaw/openclaw.json")
if not p.is_file():
    print("WARN: no openclaw.json")
else:
    cfg = json.loads(p.read_text(encoding="utf-8"))
    gw = cfg.setdefault("gateway", {})
    ui = gw.setdefault("controlUi", {})
    origins = ui.setdefault("allowedOrigins", [])
    for o in (
        f"https://{public_ip}",
        f"https://{public_ip}:443",
        f"https://{public_ip}:8080",
        f"http://{public_ip}:8080",
    ):
        if o not in origins:
            origins.append(o)
    ui["allowInsecureAuth"] = True
    ui["dangerouslyDisableDeviceAuth"] = True
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("allowedOrigins updated")
PY

nginx -t
systemctl reload nginx

# 重启网关使 Origin 生效
if systemctl is-active openclaw-gateway >/dev/null 2>&1; then
  systemctl restart openclaw-gateway || true
elif pgrep -f "openclaw gateway" >/dev/null; then
  pkill -f "openclaw gateway" || true
  sleep 1
  nohup openclaw gateway >>/root/openclaw-gateway.log 2>&1 &
fi

echo "OK https://${PUBLIC_IP}/  https://${PUBLIC_IP}:8080/  wss://${PUBLIC_IP}/ws/"
