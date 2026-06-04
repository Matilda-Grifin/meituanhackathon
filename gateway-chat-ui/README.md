# gateway-chat-ui

Minimal custom-layout chat page for an OpenClaw Gateway WebSocket. It uses [`openclaw-ws`](https://www.npmjs.com/package/openclaw-ws) (browser client with Ed25519 device identity + `connect.challenge` flow) and a patch so `connect` sends `minProtocol: 3`, `maxProtocol: 5` for negotiation with current gateways (reduces `protocol mismatch` errors).

## Prereqs

- Gateway reachable from the browser (`ws://` / `wss://`).
- Shared secret: `gateway.auth.token` (or password) — same as Control UI.
- Session key for `chat.history` / `chat.send` (copy from official Control UI session picker, or use Discover sessions and read the debug log).
- HTTPS page → WSS only (mixed content blocks `ws://` on `https://` sites).
- If UI is not on loopback: configure `gateway.controlUi.allowedOrigins` for your dev origin (e.g. `http://localhost:5173`) and complete device pairing (`openclaw devices approve …`) when the gateway closes with `1008 pairing required`.

## Run

```powershell
cd "D:\projects\meituan hackathon\meituan-lifecare-agent\gateway-chat-ui"
npm install
npm run dev
```

Open the printed `http://localhost:5173` URL, set Gateway WebSocket URL + Token, optional Session key, click Connect → Load history → type and Send.

### Query shortcuts

- `?gateway=ws://127.0.0.1:18789&token=...&session=...`
- Values are also persisted in `localStorage` (`gw.url`, `gw.token`, `gw.session`).
- Hash（不随普通请求带 Referer）：`http://IP:8080/#token=你的token`（优先级低于 query 里的 `token=`）。

## 答辩 / 评委：构建时写死网关（只打开 `http://IP:8080/`）

1. 在 `gateway-chat-ui` 目录复制环境变量模板：

   ```powershell
   copy .env.example .env.production
   ```

2. 用编辑器打开 `.env.production`（该文件已在 `.gitignore`，勿提交），至少填写：

   - `VITE_DEFAULT_GATEWAY_WS` — 例如 `ws://121.41.81.58:18789`
   - `VITE_GATEWAY_TOKEN` — 网关真实 token（会打进 `dist` 的 JS 明文，仅内网/演示）
   - 可选：`VITE_DEFAULT_SESSION_KEY`
   - `VITE_AUTO_CONNECT=true` — 打开页面后自动 Connect
   - `VITE_COMPACT_UI=true` — 隐藏三项输入框，只显示摘要与按钮
   - `VITE_SHOW_DEBUG=false` — 隐藏底部 Debug log

3. 生产构建并上传（Vite 会自动读取 `.env.production`）：

   ```powershell
   npm run build
   scp -r dist\* root@YOUR_IP:/var/www/gateway-chat-ui/
   ```

评委只需访问 `http://YOUR_IP:8080/`；若未开自动连接，仍点一次 Connect。

## If `chat.send` / `chat.history` errors

The gateway schema evolves; this demo uses a reasonable default payload:

- `chat.history`: `{ sessionKey }`
- `chat.send`: `{ sessionKey, message, idempotencyKey }`

If your gateway expects different field names, adjust `refreshHistory` / `send` in `src/App.tsx` and compare with the official Control UI or `openclaw gateway call` traces.

## Troubleshooting

- `control ui requires device identity (use HTTPS or localhost secure context)` on `http://公网IP`: the gateway treats Control UI clients as needing a secure context (HTTPS or localhost) for WebCrypto device identity. This app uses `webchat-ui` / `webchat` instead so HTTP + `ws://` can work on a LAN/public IP demo. Production should still use HTTPS + WSS.

## Patch

`patches/openclaw-ws+0.1.1.patch` sets `minProtocol: 3`, `maxProtocol: 5`. `npm install` runs `patch-package` via `postinstall`.
