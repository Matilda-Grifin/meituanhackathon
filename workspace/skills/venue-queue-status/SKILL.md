---
name: venue-queue-status
description: 可选：沙盒排队/客流演示；主链路以真实高德 POI 为准时可跳过。
---

# 排队与客流（可选沙盒演示）

## 何时使用

用户明确关心排队/拥挤，或赛题需要演示「太挤则换点」且已启动沙盒服务 时启用。

## 步骤

1. 若走沙盒：先 `lifecare__lifecare_sandbox_catalog` 取得与演示 id 对齐的 `venue_id` / `attraction_id`（仅沙盒链路需要）。
2. 餐厅：`lifecare__lifecare_get_venue_queue`；景点：`lifecare__lifecare_get_attraction_crowd`。
3. 若 `wait_minutes` 高或 `crowd_level>=4`，提供 备选 POI（仍优先真实搜点结果）。
4. 演示满座/闭店：`lifecare__lifecare_inject_sandbox_failure` 后再查一次，并口头说明为 仿真。

## 边界

- 主方案不依赖沙盒；无沙盒时本 skill 可不执行，不得声称美团真实排队数据。
- 数据来自沙盒时不得说成线上真实排队。
