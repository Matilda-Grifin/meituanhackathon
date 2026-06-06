#!/bin/bash
set -euo pipefail
REPO=/root/meituan-lifecare-agent
cd "$REPO"

python3 -m pip install -q -r requirements.txt fastapi uvicorn httpx pydantic pydantic-settings python-dotenv 2>/dev/null || \
  pip3 install -q -r requirements.txt fastapi uvicorn httpx pydantic pydantic-settings python-dotenv

if [ -f /tmp/lifecare_inject.json ]; then
  python3 << 'PY'
import json, pathlib
p = pathlib.Path("/root/meituan-lifecare-agent/.env")
inj = json.load(open("/tmp/lifecare_inject.json"))
keys = ("AMAP_KEY", "ARK_API_KEY", "ARK_BASE_URL", "ARK_MODEL_NAME", "picture_model")
lines = []
if p.exists():
    skip = set(k + "=" for k in keys)
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if not any(ln.startswith(s) for s in skip)]
for k in keys:
    v = (inj.get(k) or "").strip()
    if v:
        lines.append(f"{k}={v}")
if lines:
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
fi

cat > /etc/systemd/system/lifecare-client-context.service << 'EOF'
[Unit]
Description=Lifecare gateway client-context API (IP + regeo)
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/meituan-lifecare-agent
EnvironmentFile=-/root/meituan-lifecare-agent/.env
Environment=PYTHONPATH=/root/meituan-lifecare-agent
ExecStart=/usr/bin/python3 -m uvicorn gateway_context_api:app --host 127.0.0.1 --port 8098
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable lifecare-client-context.service
systemctl restart lifecare-client-context.service
sleep 1
systemctl is-active lifecare-client-context.service

CONF=""
for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
  [ -f "$f" ] || continue
  if grep -qE 'gateway-chat-ui|:8080' "$f" 2>/dev/null; then CONF="$f"; break; fi
done
if [ -z "$CONF" ] && [ -f /etc/nginx/sites-enabled/default ]; then
  CONF=/etc/nginx/sites-enabled/default
fi

if [ -n "$CONF" ] && ! grep -q 'location /api/' "$CONF"; then
  export CONF
  python3 << 'PY'
import pathlib, re, os
conf = pathlib.Path(os.environ["CONF"])
text = conf.read_text(encoding="utf-8")
snippet = """
    location /api/ {
        proxy_pass http://127.0.0.1:8098;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
"""
if "location /api/" not in text:
    m = re.search(r"(server\s*\{[^}]*listen\s+8080[^}]*)(\})", text, re.S)
    if m:
        text = text[: m.end(1)] + snippet + text[m.end(1) - 1 :]
    else:
        idx = text.find("server {")
        if idx >= 0:
            ins = text.find("{", idx) + 1
            text = text[:ins] + snippet + text[ins:]
    conf.write_text(text, encoding="utf-8")
    print("patched", conf)
PY
fi

nginx -t
systemctl reload nginx

# 确保 /ws/ 长连接超时（国内长 run 流式 + 工具调用，默认 60s 易断）
if [ -n "$CONF" ]; then
  export CONF
  python3 << 'PY'
import pathlib, re, os
conf_path = os.environ.get("CONF", "")
p = pathlib.Path(conf_path)
if not p.is_file():
    print("skip ws timeout patch:", conf_path)
else:
    text = p.read_text(encoding="utf-8")
    if "location /ws/" in text and "proxy_read_timeout 86400" not in text:
        text = re.sub(
            r"(location /ws/\s*\{)",
            r"\1\n        proxy_read_timeout 86400s;\n        proxy_send_timeout 86400s;",
            text,
            count=1,
        )
        p.write_text(text, encoding="utf-8")
        print("patched ws timeouts in", conf_path)
    else:
        print("ws timeouts ok in", conf_path)
PY
  nginx -t
  systemctl reload nginx
fi

# 行程信息图：LLM 抽取 + Seedream 常 >60s，/api/ 需拉长 nginx 超时（默认 60s → 504）
if [ -n "$CONF" ]; then
  export CONF
  python3 << 'PY'
import pathlib, re, os
conf_path = os.environ.get("CONF", "")
p = pathlib.Path(conf_path)
if not p.is_file():
    print("skip api timeout patch:", conf_path)
else:
    text = p.read_text(encoding="utf-8")
    if "location /api/" in text and "proxy_read_timeout 360" not in text:
        text = re.sub(
            r"(location /api/\s*\{[^}]*?proxy_set_header X-Forwarded-Proto[^\n]+\n)",
            r"\1        proxy_read_timeout 360s;\n        proxy_send_timeout 360s;\n",
            text,
            flags=re.DOTALL,
        )
        p.write_text(text, encoding="utf-8")
        print("patched api timeouts in", conf_path)
    else:
        print("api timeouts ok in", conf_path)
PY
  nginx -t
  systemctl reload nginx
fi

echo -n "health: "
curl -sf http://127.0.0.1:8098/health && echo
echo -n "api: "
curl -sf http://127.0.0.1:8098/api/client-context | head -c 500 && echo
echo -n "nginx_api: "
curl -skf https://127.0.0.1:8080/api/client-context | head -c 500 && echo
