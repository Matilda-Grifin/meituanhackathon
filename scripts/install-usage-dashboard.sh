#!/usr/bin/env bash
# Install LifeCare usage dashboard (port 8849) on OpenClaw server.
set -eu

REPO="${LIFECARE_REPO:-${MEITUAN_REPO:-$HOME/meituan-lifecare-agent}}"
WS="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
PORT="${USAGE_DASHBOARD_PORT:-8849}"
TOKEN="${USAGE_DASHBOARD_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  TOKEN="$(openssl rand -hex 12)"
  echo "Generated USAGE_DASHBOARD_TOKEN=$TOKEN"
fi

ENV_FILE="$WS/.env"
mkdir -p "$(dirname "$ENV_FILE")"
grep -q '^USAGE_DASHBOARD_TOKEN=' "$ENV_FILE" 2>/dev/null || \
  echo "USAGE_DASHBOARD_TOKEN=$TOKEN" >> "$ENV_FILE"

export OPENCLAW_WORKSPACE="$WS"
export LIFECARE_REPO="$REPO"
python3 "$REPO/scripts/usage-collector.py" --mode all >/dev/null

UNIT="$HOME/.config/systemd/user/lifecare-usage-dashboard.service"
mkdir -p "$(dirname "$UNIT")"
cat > "$UNIT" <<EOF
[Unit]
Description=LifeCare usage dashboard (online + eval)
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO/dashboard
Environment=OPENCLAW_WORKSPACE=$WS
Environment=LIFECARE_REPO=$REPO
Environment=USAGE_DASHBOARD_PORT=$PORT
Environment=USAGE_DASHBOARD_TOKEN=$TOKEN
ExecStart=/usr/bin/node $REPO/dashboard/server.js
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable lifecare-usage-dashboard.service
systemctl --user restart lifecare-usage-dashboard.service

echo ""
echo "Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_SERVER_IP'):$PORT/?token=$TOKEN"
echo "Local:     http://127.0.0.1:$PORT/?token=$TOKEN"
echo ""
echo "Tab 1: 线上真实费用 | Tab 2: 测试看板"
echo "改单价: $REPO/dashboard/pricing.json 后点「立即刷新」"
echo "若外网打不开，请在云厂商安全组放行 TCP $PORT"
