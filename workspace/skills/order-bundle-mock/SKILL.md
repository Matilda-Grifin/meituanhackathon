---
name: order-bundle-mock
description: 可选：用户明确确认后沙盒 Mock 下单演示；真实订座以业务系统为准，本 skill 不冒充。
---

# Mock 一键下单（可选演示）

## 何时使用

用户明确说 确认方案 / 演示一键下单 / 赛题异常流程，且团队已启用沙盒 时使用。

## 步骤

1. 复述将下单的 `restaurant_id`（沙盒 catalog 内）、人数、时段。
2. `lifecare__lifecare_submit_mock_order`，`extras` 为 JSON 数组字符串，如 `["蛋糕","鲜花"]`。
3. 异常演示：`force_failure` 取 `full` | `closed` | `conflict` 之一，再说明 重规划。
4. 成功则读出 `order_id`（Mock）。

## 边界

- 默认主链路不使用；真实高德 POI 与沙盒 id 无映射时不得强行下单。
- 不产生真实支付；不得收集真实手机号/身份证。
