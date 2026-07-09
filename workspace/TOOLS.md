# 工具速查（MCP: lifecare）

在 OpenClaw 网关里，stdio MCP 服务器名为 `lifecare` 时，工具对外 id 为 `lifecare__` + 下表中的原名（双下划线是命名空间，与 `run_mcp.py` 里 Python 函数名 `lifecare_*` 不同，调用工具时必须写带前缀的全名）。

| 工具名 | 用途 | 主链路 |
|--------|------|--------|
| `lifecare__lifecare_get_weather` | 高德天气多天预报（`provider=amap`）；失败时 Open-Meteo 兜底；参数 `city`、`forecast_days`（1–16，高德最多 4 天）；`daily[]` 含 `date`/`weather`/`temp_max_c`/`temp_min_c` | 常用 |
| `lifecare__lifecare_search_places` | 高德 POI 关键字搜索；默认 `extensions=all` 并带 `reputation`（高德 rating 若存在 + 确定性 mock 口碑，全国可测） | 常用 |
| `lifecare__lifecare_plan_route` | 高德驾车距离/时间 | 常用 |
| `lifecare__lifecare_sandbox_catalog` | 沙盒餐厅/景点 id | 可选（沙盒演示） |
| `lifecare__lifecare_get_venue_queue` | 沙盒餐厅排队 | 可选 |
| `lifecare__lifecare_get_attraction_crowd` | 沙盒景点拥挤度 | 可选 |
| `lifecare__lifecare_ride_estimate` | 沙盒打车估算 | 可选 |
| `lifecare__lifecare_submit_mock_order` | 沙盒 Mock 下单 | 可选 |
| `lifecare__lifecare_inject_sandbox_failure` | 注入满座/闭店等 | 可选 |

配置方式见 `reference/openclaw-mcp.snippet.json5`。

## MCP 侧耗时日志

默认写入 `benchmark/results/mcp_tool_calls.jsonl`。在 `mcp.servers.lifecare.env` 中设 `LIFECARE_MCP_TOOL_LOG=0` 关闭；可选 `LIFECARE_MCP_TOOL_LOG_PATH` 自定义路径。这不替代 OpenClaw 自带会话日志。
