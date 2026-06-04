# 自建对话页 / 云上给别人用（与 OpenClaw 的关系）

## 本地 / 阿里云：独立门户（不影响其他端口）

- `index.html`：本目录的门户首页（深色样式 + 本地/阿里云说明 + 工具链接）。  
- `serve_landing.py`：只托管 `web/`，默认 `127.0.0.1:8765`；云上可加 `--host 0.0.0.0 --port 8765`，安全组只放行该端口即可，与 OpenClaw 18789、其他项目隔离。

```powershell
cd "D:\projects\meituan hackathon\meituan-lifecare-agent\web"
python serve_landing.py
# 浏览器打开 http://127.0.0.1:8765/
```

自建对话（不经过 OpenClaw）：在项目根目录另起服务（默认 8099）：

```powershell
cd "D:\projects\meituan hackathon\meituan-lifecare-agent"
python -m uvicorn web_server_chat:app --host 127.0.0.1 --port 8099
# 浏览器打开 http://127.0.0.1:8099/
```

页面 `web/lifecare-chat.html`：气泡 + Markdown；`POST /api/chat` 调 `run_dry` / `run_llm`。

## 能不能「自己开发一个对话网页 + 图 + 选项」？

可以，分三档，推荐黑客松用 A 或 B。

| 方案 | 是否复用 OpenClaw 现成前端 | 图 / 选项 | 工作量 |
|------|---------------------------|-----------|--------|
| A | 完全复用：用户只打开网关上的 Control UI（同一进程提供静态页 + WS） | 助手回复里用 Markdown 插图、文字选项即可（模型 + MCP 已支持） | 最小：HTTPS/WSS、防火墙、鉴权按需 |
| B | 复用同一套 UI 静态资源：把全局包里的 `dist/control-ui` 拷到 OSS/Nginx，用官方支持的 `?gatewayUrl=...#token=...` 连远端网关 | 同上 | 中小：要配 `gateway.controlUi.allowedOrigins` 为你的静态页域名 |
| C | 不复用：自写 SPA，自己接网关 WebSocket 协议 | 自己用 marked 等渲染 Markdown；选项用按钮往输入框塞一句话 | 大：协议与鉴权都要对齐官方 |

官方说明（远程静态 UI + `gatewayUrl`）：[Control UI · Debugging/testing](https://docs.openclaw.ai/web/control-ui)。

## 本目录文件

- `lifecare-chat.html` + 根目录 `web_server_chat.py`：独立对话 UI（不经 OpenClaw），`uvicorn web_server_chat:app --port 8099`。  
- `serve_landing.py`：静态服务，默认端口 8765。  
- `judge-launch.html`：评委一键进对话。打开后立刻 `location.replace` 到 OpenClaw Control UI；部署前在文件内改 `OPENCLAW_HOME`（及可选 `AUTH_FRAGMENT`），发链接 `.../judge-launch.html` 即可，无需填 WebSocket 表单。  
- `control-ui-launcher.html`：仅当「静态 UI 与网关不同源」时用，需填 `gatewayUrl` / token。  
- `rich-reply-preview.html`：粘贴助手 Markdown，预览选项/图。

## 阿里云给别人用（要点清单）

1. ECS 上跑 OpenClaw Gateway（或 Docker），对外只开 443（HTTPS）与 WSS。  
2. Nginx / Caddy 反代到网关端口，证书用 Let’s Encrypt 或阿里云 SSL。  
3. `openclaw.json`：鉴权按你需求配置；若静态页与网关不同域名，需配置 `gateway.controlUi.allowedOrigins` 为静态页的完整 Origin。  
4. 方案 A：用户访问 `https://你的网关域名/` 即可聊天。  
5. 方案 B：静态 UI 在 `https://static.xxx/`、网关在 `https://gw.xxx/`，用本仓库 `control-ui-launcher.html` 拼链接，或按官方文档手写 `gatewayUrl`。  
6. 图：继续靠助手 Markdown（`![](photo_urls)` 等）；选项：继续靠模型输出 A/B/C 或你做「快捷回复」属于方案 C 的扩展。

### 答辩 / 自用：鉴权按你方便来

按你的计划即可：可暂时关鉴权或放宽，继续用你现在的 模型 / 高德 Key；事后自行轮换 Key 即可。文档不再展开安全清单；现场节奏由你自己把握。

## 前端交互想「完全按我要求」——和用不用 Lit 无关

你关心的是 交互能不能定制，不关心底层叫 Lit 还是别的：

| 你的目标 | 谁能改交互 | 说明 |
|----------|------------|------|
| 继续用 OpenClaw 网关里的 Agent（MCP、多轮、流式） | 聊天壳要么 fork 官方 Control UI 改交互，要么 自写网页 + 自己对接网关 WebSocket 协议（工作量大）。FastAPI / Streamlit 可以当 外壳（入口、说明、反代静态页），但替代不了「浏览器 ↔ 网关」这条 WS 链路本身。 |
| 交互你说了算、可以不要 OpenClaw 网页 | 用 FastAPI / Streamlit + `run_local_agent.py` 或直接调 MCP`，整页按钮、表单、图床都由你写；代价是 赛题里「基于 OpenClaw」 要你自己和评委对齐表述（网关是否仍算 OpenClaw 在跑）。 |

一句话：技术名字不重要；要 OpenClaw 网关那套能力，交互大改就 fork 官方 UI 或重写 WS 客户端；只在乎交互、可弱化网关 UI，就上 FastAPI/Streamlit + 本仓库 Agent/MCP 链路。

## 这个项目能上阿里云吗？要先装 OpenClaw 再打包吗？

可以上云。推荐理解成 两台「逻辑组件」（可同一台 ECS 上跑）：

| 组件 | 是什么 | 上云方式 |
|------|--------|----------|
| ① OpenClaw Gateway | Node 安装的 `openclaw`，读 `~/.openclaw/openclaw.json`，对外 18789（或经 Nginx 443） | 云服务器上 先装 Node + 全局 `openclaw`（或官方 Docker），再配 `openclaw.json`。 |
| ② 本仓库 `meituan-lifecare-agent` | Python MCP（`run_mcp.py`）+ 可选沙盒 `sandbox/` | 把整个目录拷到 ECS（git clone / scp），`python -m venv` + `pip install -r requirements.txt`；在 `openclaw.json` 的 `mcp.servers.lifecare` 里把 `command`/`args`/`PYTHONPATH` 指到 云上的绝对路径；`.env` 放 云上专用 Key。 |

推荐顺序（同一台 ECS 最简）：

1. 装 Node、Python 3.11+，`npm i -g openclaw`，`openclaw onboard` / 拷好 `openclaw.json`。  
2. clone 本仓库，建 venv，`pip install -r requirements.txt`。  
3. 编辑云上 `openclaw.json`：`lifecare` MCP 指向 `/opt/.../meituan-lifecare-agent/run_mcp.py` 与 venv 里的 `python`；`MOCK_SANDBOX_BASE_URL`、`AMAP_KEY` 写在 `lifecare.env` 或 `.env`。  
4. （可选）`uvicorn sandbox.main:app --host 127.0.0.1 --port 9000` 用 systemd 保活。  
5. 启动网关 `openclaw gateway`（或 daemon），Nginx TLS 反代到网关。  
6. workspace：`openclaw.json` 里 agent 的 `workspace` 指到云上本仓库的 `.../meituan-lifecare-agent/workspace`。

不是「只把 Python 项目打成 zip 丢上去就能替代 OpenClaw」——赛题链路里 网关仍要跑；本仓库是 MCP + 人设 + 沙盒，挂在网关下面。

## 与赛题 MCP 的关系

对话页只负责 展示与连接网关；高德 / 天气 / 沙盒仍由网关拉起本项目的 `run_mcp.py`，与是否自建 HTML 无关。

---

## 常见疑问（WebSocket / 鉴权 /「重做网页」）

### 不用 WebSocket 行不行？

- 要用 OpenClaw 网关里的完整 Agent（多轮、流式、MCP 工具、会话存档），官方浏览器路径就是 WebSocket（`chat.history` / `chat.send` 等，见 [Control UI](https://docs.openclaw.ai/web/control-ui)）。  
- 没有「只开 HTTP 就能等价替代」的通用公开接口可以偷懒接上；若完全不用 WS，等于 不要 OpenClaw 网关，改为你自写后端直连大模型 + 自己调 `run_mcp.py`（与赛题「基于 OpenClaw」可能冲突，且工作量大）。

### 公网上不要鉴权行不行？

答辩 / 自用场景按 `openclaw.json` 里你的设置即可；与上文 「答辩 / 自用：鉴权按你方便来」 一致。

### 「重做网页」我能在这仓库里做到什么程度？

| 目标 | 现实做法 |
|------|----------|
| 体验和官方 Control UI 一模一样还能随便改皮肤 | 需要 fork OpenClaw 前端（Lit）再 `pnpm ui:build`，不在本业务仓库内。 |
| 先验证 选项 + 图 在浏览器里长什么样 | 用本目录 `rich-reply-preview.html`：粘贴助手 Markdown 即可预览（不连网关）。 |
| 正式可点的「自定义聊天站」且仍用 OpenClaw Agent | 走 方案 C：自写 SPA + 完整实现网关 WS 协议与鉴权；工作量以「周」计，且要跟着官方版本更新。 |

结论：交互大改 ↔ 仍走 OpenClaw 网关 Agent 时，要么 fork 官方 UI / 自写 WS 客户端，要么接受官方 UI + 用 `SOUL.md` / `rich-reply-preview.html` 把版式压到模型侧；只在乎交互可走 FastAPI/Streamlit + 本仓库工具链。
