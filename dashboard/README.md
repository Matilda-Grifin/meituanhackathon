# 现在就出发 · 费用看板

双 Tab 用量与估算费用：**线上真实费用** / **测试看板**（6.3 测评）。不展示 ECS 固定基础设施成本。

## 快速启动（ECS / 本机）

```bash
# 1. 采集统计（线上 + 测评各一份 JSON）
export OPENCLAW_WORKSPACE=~/.openclaw/workspace
export LIFECARE_REPO=/path/to/meituan-lifecare-agent
python3 scripts/usage-collector.py --mode all

# 2. 启动看板（默认 8849）
export USAGE_DASHBOARD_TOKEN=your-secret
node dashboard/server.js
```

浏览器打开：`http://127.0.0.1:8849/?token=your-secret`

## systemd 安装

```bash
bash scripts/install-usage-dashboard.sh
```

## 数据来源

| Tab | 文字 Token | MCP | 测评 LLM |
|-----|-----------|-----|----------|
| 线上真实费用 | 非 `v63-` session 的 OpenClaw trajectory | `测试/results/mcp_tool_calls.jsonl` | — |
| 测试看板 | `v63-` session trajectory | 不计入（避免重复） | `logs/eval-llm-usage.jsonl` + `*_run.json` 的 `token_usage` |

新跑 6.3 batch 后，`orchestrator` 会在 `*_run.json` 写入 `token_usage`（agent / user_sim / judge）；用户模拟与裁判调用同时追加到 `eval-llm-usage.jsonl`。

## 改单价

编辑 `dashboard/pricing.json`，看板点「立即刷新」即可，无需重启 Node。

## 安全

- 必须带 `?token=` 访问 API（与 accompany 8848 相同机制）
- 云安全组需放行 **8849**（与 accompany 8848 区分）

## 相关文档

- [docs/费用看板/技术方案.md](../docs/费用看板/技术方案.md)
