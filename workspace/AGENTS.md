# Workspace · 本地生活黑客松

本目录文件可整体复制到 OpenClaw 默认 workspace（例如 `~/.openclaw/workspace`）或你在 `openclaw.json` 里为赛题 agent 指定的目录。

本地从浏览器对话到 MCP 的整体流程：见同目录 `OPENCLAW_本地联调流程.md`。

## 启动时

- 阅读 `SOUL.md`、`MEMORY.md`（本赛题为模拟偏好）；演示用户与短评种子见 `mock/user_and_reviews.seed.json`（当前 18 个虚构用户、22 条虚构短评，可按 `user_id` 选用）。
- `skills/` 下 6 个技能为赛题能力说明；主链路以 真实高德 + 天气 为准，用户偏好与评价语料为 mock（见 `mock-user-prefs-reviews`）；沙盒工具仅 可选演示。

## 工具来源

- 高德 POI / 驾车路线、高德天气（Open-Meteo 兜底）：由 MCP `lifecare__lifecare_*`（OpenClaw 对 `mcp.servers.lifecare` 的命名空间前缀 + `run_mcp.py` 内工具名）提供（见项目 `run_mcp.py`）。
- 排队/客流/Mock 下单/沙盒 catalog：可选；由 沙盒 FastAPI 提供，仅演示时启动 `uvicorn sandbox.main:app --port 9000`。

## MCP 工具耗时日志

默认开启：每次 `lifecare__lifecare_*` 调用会追加到 `benchmark/results/mcp_tool_calls.jsonl`（仅工具名、耗时、是否报错）。在 `openclaw.json` 的 `mcp.servers.lifecare.env` 里设 `LIFECARE_MCP_TOOL_LOG=0` 可关闭；可选 `LIFECARE_MCP_TOOL_LOG_PATH` 自定义 JSONL 路径。完整对话仍看 OpenClaw 日志与会话 JSONL。

## 演示 SLA（团队自定）

- 槽位不齐：首条回复只做 2～3 个选择题，不调搜点/算路工具，保证首字快（见 `SOUL.md`）。
- 槽位齐：首字 ≤ 10s：先一句「正在查天气/搜点…」再并行工具；完整方案 ≤ 3min，且须 长文 + 表格 + 预算 + Tips（对齐 `理想回答.md` 密度，见 `local-itinerary-planner`）。
