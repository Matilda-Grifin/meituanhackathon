---
name: route-and-mobility
description: 本地段用高德驾车路径；多段串联支撑每日多 POI；大交通不伪造票务；可选沙盒打车估算仅作说明。
---

# 路线与出行

## 何时使用

动线中任意相邻 POI 需要 时间/距离，或用户问「这段开车多久」；一日内多点时需对相邻段 多次 调用并串联。

## 步骤

1. 从 `lifecare__lifecare_search_places` 结果取 `location.lng/lat`；缺失则不要猜测坐标。
2. 对相邻两段调用 `lifecare__lifecare_plan_route`，得到 `distance_m`、`duration_s`；按 planner 给出的顺序逐段拼接全日时间轴。
3. 交通语义：自驾/本地出租 用驾车路径作参考；地铁 若 MCP 未提供轨交路径，则用文字说明「需用户用地图 App 轨交规划」勿编造精确换乘。
4. 高铁/跨城：不调用虚构票务 API；仅说明时段假设与到站后接入本地 `plan_route` 的起点。
5. 可选：需演示打车区间时 `lifecare__lifecare_ride_estimate(distance_m=..., traffic=normal|heavy)`，并注明 沙盒仿真非实时计价。

## 边界

- 不把沙盒打车当作滴滴/高德真实账单。
- 成对点数较多时注意并行或批处理意识，避免单轮超时；仍无法满足 SLA 时先返回骨架顺序再补全路段。
