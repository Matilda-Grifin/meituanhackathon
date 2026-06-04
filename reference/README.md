本目录为从 OpenClaw 仓库 对照用 的片段，便于答辩时说明「如何接入官方 MCP 机制」。

- `openclaw-mcp.snippet.json5`：网关 `mcp.servers` 配置示例。
- 完整插件（TypeScript `extensions/*`）体积大，本赛题用 Python MCP + 沙盒 满足「工具 + Skill」演示即可；若需原生插件形态，再在 `openclaw-main` 里按 `openclaw.plugin.json` 规范扩展。
