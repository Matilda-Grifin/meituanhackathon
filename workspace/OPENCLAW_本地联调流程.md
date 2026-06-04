# OpenClaw 本地联调：从浏览器到 MCP（整体流程）

面向「本机已经能跑 OpenClaw」时的一条线说明；若你要改 Control UI 界面，见下文 §5。

## 1. 你这边要开什么

1. OpenClaw 网关（本机常见端口 18789）。
2. 浏览器打开 Control UI：`http://127.0.0.1:18789/`（或 `http://localhost:18789/`）。
3. 在界面里选中你为黑客松配的 Agent（例如 `lifecare-demo`），再进 聊天 / WebChat。
4. 可选：若要用沙盒排队/下单，另开一个终端起 FastAPI 沙盒（见项目根目录 `README.md`）。

## 2. 发一条用户消息后，背后发生什么

```
你在网页里打字
    → 浏览器通过 WebSocket 连到本机 Gateway
    → Gateway 把话交给当前 Agent 绑定的模型（如豆包）
    → 模型决定要不要调用「工具」
    → 若调用 lifecare_*：Gateway 会启动/复用 MCP 子进程（跑本仓库的 run_mcp.py）
    → MCP 里执行高德 / 天气 / 沙盒 HTTP，把 JSON 字符串还给模型
    → 模型继续推理，流式把最终中文回答写回网页
```

网页本身不限制「先反问再查地图」——快慢和内容主要由 模型 + workspace 里的 SOUL / Skill 说明 决定；本仓库已把「槽位不齐先 2～3 个选择题、齐了再给长方案」写进 `SOUL.md` 与 `travel-intake`。

## 3. 人设、技能、工具各在哪

| 东西 | 在哪 |
|------|------|
| 管家人设、首字 SLA、输出习惯 | `SOUL.md`、`AGENTS.md` |
| 反问槽位、动线结构 | `skills/travel-intake`、`skills/local-itinerary-planner` 的 `SKILL.md` |
| 真查地图/天气/路线 | OpenClaw 里注册的 MCP：`lifecare_*`（本仓库 `run_mcp.py`） |

Agent 的 `workspace` 在 `openclaw.json` 里必须指到本目录（或你复制后的同名目录），否则读不到上述文件。

## 4. 日志：完整对话 vs 工具耗时

| 需求 | 怎么做 |
|------|--------|
| 双方对话 + 工具调用（OpenClaw 侧） | 用官方 CLI：`openclaw logs --follow`（或文档中的等价命令）；持久内容一般在 Agent 目录下的会话 JSONL（由网关/Pi 写入，版本不同路径略有差异，可在 `~/.openclaw/agents/<你的 agent>/` 下搜 `.jsonl`）。 |
| 每个 lifecare 工具耗时（本项目可测） | 默认追加到 `benchmark/results/mcp_tool_calls.jsonl`；要关掉则在 `lifecare.env` 设 `LIFECARE_MCP_TOOL_LOG=0` 并重启网关。 |

## 5. Control UI 源码在哪、能不能改工具气泡 / 展开 JSON / 耗时

官方说明：网关上的 Control UI 是 Vite + Lit 打的静态资源，默认打进 `dist/control-ui`，由网关在 同一端口（如 18789）提供；构建命令见 OpenClaw 仓库文档：`pnpm ui:build`（见官方 `docs/web/index.md` → *Building the UI*）。

- 你黑客松目录里的 `openclaw-main`：若只有 `extensions/`、`docs/` 等而 没有完整 `scripts/`、`ui/` 包，说明是裁剪/不完整克隆，本地可能找不到 Control UI 前端源码；需要到 完整仓库 [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw) 再拉一份，在仓库内搜 `control-ui`、`ui:build` 定位具体子目录（不同版本路径可能调整，以该仓库 `package.json` 为准）。
- 全局 `npm i -g openclaw` 安装的包：源码/构建产物在 本机 npm 全局目录 下的 `node_modules/openclaw/`（路径因 Node 安装方式而异，可用 `npm root -g` 查看），里面通常带 已构建的 `dist/control-ui`；要改气泡样式需 fork 官方仓库 → 改 Lit 组件 → 再 `pnpm ui:build` → 用你构建的网关/包替换，工作量属于「 fork 框架」，不是黑客松业务仓库里改两行能搞定。

结论：可以改，但要在 OpenClaw 主仓库 + 前端构建链 里做；你当前业务项目里的 `openclaw-main` 若缺 UI 子工程，需要先补全克隆。

### 5.1 你列的本机路径：各自是什么、去哪找「能改 UI 的源码」

Cursor 里我不一定能读到你 C 盘用户目录；请你在 本机 PowerShell 自己 `dir` / 资源管理器对照下表：

| 路径 | 一般是什么 |
|------|------------|
| `C:\Users\19200\.openclaw` | 配置与 Agent 数据（`openclaw.json`、agents、workspace 副本），不是 Control UI 前端源码。 |
| `C:\Users\19200\.openclaw\workspace\.openclaw` | 多为 工作区/缓存，不是 UI 工程。 |
| `C:\Users\19200\.cursor\projects\...` | Cursor 打开过的项目副本/索引，是否含完整 OpenClaw 以你本机为准。 |
| `C:\Users\19200\.zagent\openclaw` | 第三方/工具链目录，未必是官方 monorepo。 |
| `C:\Users\19200\Desktop\openclaw`、`D:\projects\qq_openclaw`、`Downloads\openclaw-main\...` | 若含完整 git 仓库，在根目录执行 `Get-ChildItem -Recurse -Directory -Filter "dist" \| ? { $_.FullName -match "control-ui" }` 找 `dist/control-ui`；含 `.ts` / `.lit` 源码的包名常见带 `control`、`ui`（以你克隆版本为准）。 |
| `D:\nodejs\node_global\node_modules\openclaw` | npm 全局安装的包：优先找子目录 `dist/control-ui`（已构建静态页）；改气泡仍要回到官方源码 fork 后重打 `pnpm ui:build`。 |

实用命令（在你自己电脑上跑）：

```powershell
npm root -g
# 对上表 node_global 路径执行：
Get-ChildItem "D:\nodejs\node_global\node_modules\openclaw" -Recurse -Depth 5 -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq "control-ui" -and $_.PSIsContainer }
```

已验证示例（本机 npm 全局包）：若输出为  
`D:\nodejs\node_global\node_modules\openclaw\dist\control-ui`  
则说明 Control UI 已构建的静态资源在这里；要改界面仍需 fork 官方源码改 Lit 后重跑 `pnpm ui:build`，再替换/链接你自编的网关包，不能只改这个 dist 目录里压缩后的文件长期维护。

### 5.2 「选项 + 配图」：我能在哪改、不能在哪改

| 你想要的效果 | 在 本黑客松仓库里能不能改 | 说明 |
|--------------|------------------------------|------|
| Control UI 里工具气泡（展开 JSON、显示每工具毫秒耗时条等） | 不能（不在本仓库） | 要改 OpenClaw 官方源码（Lit）→ `pnpm ui:build` → 用自构建网关；或接受现状，用 `openclaw logs` + `mcp_tool_calls.jsonl` 看细节。 |
| 对话里的「2～3 个选项」（A/B/C 反问） | 能 | 已写在 `SOUL.md`、`skills/travel-intake/SKILL.md`；靠模型遵守，不是改 `dist/control-ui`。 |
| 对话里的配图（用户能在聊天里看到图） | 能（走模型 Markdown） | MCP 已给 POI 的 `photo_urls`、`amap_place_url`；模型在回复里写 `![](图片地址)` 或 `[地名](高德链接)`，WebChat 一般按 Markdown 渲染图片（以你当前 OpenClaw 版本为准）。不能指望我在 `dist/control-ui` 里替你加一套新图库组件而不 fork。 |

结论：「选项 + 配图」应在对话内容层解决（本仓库已铺数据 + prompt）；「改 OpenClaw 网页壳/气泡」不在本仓库能力内，除非你 fork 官方 UI。若需自建/云上托管对话入口，见项目 `web/README.md`（方案 A/B/C + 阿里云要点 + `control-ui-launcher.html`）。

## 6. 沙盒 502：白话 + 你能怎么做

### 一句话

502 = 浏览器/MCP 去访问你配置的沙盒地址（默认 `http://127.0.0.1:9000`）时，对面回了「网关错误」——多半是 9000 上不是咱们这个 FastAPI，或 前面还有一层 Nginx/Caddy 把请求转坏了。正常跑着的本沙盒对客流接口会直接回 200 + JSON，不会自己造 502。

沙盒接口走的是 本机回环 HTTP（127.0.0.1），不依赖上公网；所谓「联网错误」一般是 连不上本机 9000 或 被错误的服务/反代回了 502，不是高德那种外网 API。

### 你要做的（三选一）

1. 要用沙盒：在项目目录起 `uvicorn sandbox.main:app --host 127.0.0.1 --port 9000`，浏览器能打开 `http://127.0.0.1:9000/docs`。  
2. 不用沙盒：在 `openclaw.json` 里把 `lifecare__lifecare_get_attraction_crowd`（等沙盒工具）从 `alsoAllow` 删掉，模型就不会调。  
3. 怕环境变量没进 MCP：在 `lifecare.env` 里写死 `MOCK_SANDBOX_BASE_URL=http://127.0.0.1:9000`。

### 本仓库已替你改好的（少踩坑）

从 `run_mcp.py` 起：沙盒 连不上、HTTP 4xx/5xx（含 502） 时，工具不再抛异常，而是返回一段 `{"ok":false,...,"hint_zh":"..."}` 的 JSON 字符串，模型能读到原因；超时改为 6 秒，避免卡太久。完整对话仍以 OpenClaw 日志 / 会话 JSONL 为准。

### 一键自检（答辩 / CI 前）

在项目根目录（已起沙盒或准备起沙盒的机器上）：

```powershell
cd "D:\projects\meituan hackathon\meituan-lifecare-agent"
.\.venv\Scripts\python.exe scripts\check_sandbox.py
```

成功打印 `OK: http://127.0.0.1:9000 health + crowd` 且退出码 0；失败则 1 并提示先起 `uvicorn`。可用环境变量 `MOCK_SANDBOX_BASE_URL` 指向别的地址做检查。

## 6. 自研前端界面，但仍用 OpenClaw Gateway（不经 18789 同源的「官方首页」）

目标：浏览器不打开网关根路径那张默认 Control UI，但会话、流式、MCP 仍由网关负责（与 macOS WebChat 同一类：直连 Gateway WebSocket）。

### 6.1 官方已写清楚的聊天 RPC（自定义客户端要对齐的核心）

- 连接：与 Control UI 一样，在本机网关端口上建 WebSocket；鉴权在握手阶段通过 `connect.params.auth.token` / `password`（见 [Control UI](https://docs.openclaw.ai/web/control-ui) 文档 *Auth* 一节）。
- 聊天最少集：`chat.history`、`chat.send`、`chat.abort`（可选 `chat.inject`）；`chat.send` 非阻塞，正文通过后续 `chat` 事件流式回来（见同一文档 *Send and history semantics*）。
- 行为细节（历史截断、`sessionKey`、展示归一化等）：[WebChat](https://docs.openclaw.ai/web/webchat) 与 Control UI 文档交叉阅读。

完整方法名表、设备配对、`/__openclaw/control-ui-config.json` 等仍以官方文档为准；协议级 JSON 字段的权威来源是 OpenClaw 仓库里 Control UI / 网关的实现（自定义壳 = 自己实现同一套 RPC 与事件订阅）。

### 6.2 三档工作量（黑客松怎么选）

| 档位 | 做法 | 自定义程度 |
|------|------|------------|
| 轻 | 仍用官方构建的 `dist/control-ui`，托管在你自己的域名 / 端口，用查询参数 `?gatewayUrl=...`（token 用 `#token=...`）指向网关；网关配置 `gateway.controlUi.allowedOrigins` 包含你的静态页 Origin。 | 域名、入口页、运维；聊天区仍是官方 Lit UI |
| 中 | Fork [openclaw/openclaw](https://github.com/openclaw/openclaw)，在 `pnpm ui:dev` / `ui:build` 那条链上改主题与布局（仍是官方 SPA）。 | 交互与样式可控，跟上游合并成本 |
| 重 | 自写任意前端栈，自行实现与网关的 WebSocket RPC（对齐上表 RPC + 流式事件）；设备配对、HTTPS/WSS、`allowedOrigins` 都要自己踩一遍。 | 完全自定义；工期与排错明显高于本仓库 8099 + `run_local_agent` |

调试远程网关 + 本地 UI：`http://localhost:5173/?gatewayUrl=ws%3A%2F%2F...` 的写法见官方 [Control UI · Debugging/testing](https://docs.openclaw.ai/web/control-ui)。

### 6.3 和本仓库 8099 自建对话的区别

- 走网关的自研壳：仍是 OpenClaw 运行时（评委问「是不是 OpenClaw」可理直气壮说是）。
- `web_server_chat.py` + `run_local_agent`：不连网关，只复用 MCP 实现；答辩口径需与赛题要求对齐。
