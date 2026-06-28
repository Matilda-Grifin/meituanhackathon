# 11 模型 × 3 任务 · 人工评测进度与打分

> **日志源**：ECS `测试/eval_logs/eval_manual_YYYY-MM-DD.jsonl`  
> **自动 rubric**：`python3 测试/manual_eval/score_from_logs.py --date YYYY-MM-DD`  
> **排查文档**：[`待修复/007_…追问阶段路由与第二轮Intake展示.md`](../../../待修复/007_排查与修复方案_追问阶段路由与第二轮Intake展示.md)

**任务集**：

| Task | 难度 | 轮次 |
|------|------|------|
| T063_002 | easy | 3 |
| T063_034 | medium | 4 |
| T063_048 | hard | 5 |

**模型**（11）：doubao-seed-2.0-code · doubao-seed-2.0-pro · doubao-seed-2.0-lite · doubao-seed-code · minimax-m2.7 · minimax-m3 · glm-4.7 · deepseek-v4-flash · deepseek-v4-pro · kimi-k2.6 · kimi-k2.7-code

---

## 打分说明

| 列 | 含义 |
|----|------|
| **reward** | rubric 自动分 `met/total`（跑 score_from_logs 后填） |
| **phase_route** | 阶段路由：追问是否误 re-intake / 是否该调工具未调 |
| **ui** | 前端：第二轮 intake 是否可展示等 |
| **session** | OpenClaw sessionUuid 前缀，便于查 jsonl |

**phase_route 标记**：

- `OK` 符合 SOUL 大阶段二
- `RE-INTAKE` 小改/补约束却再出选择题（Agent）
- `NO-TOOL` 模式②改方案但未调 search/weather（Agent）
- `SKIP-DECL-ONLY` 口语跳过 B 阶段：仅输出「不再重复问卷…正在查…」声明，**未 emit tool_calls、无方案**（Agent · 006 复测 2026-06-25）
- `NO-LINK` 方案 POI 无 amap link（常伴随 NO-TOOL）
- `UI-INTAKE` intakeLocked 导致第二轮选择题不可见（前端）

---

## 进度矩阵

| 模型 | T063_002 | T063_034 | T063_048 |
|------|----------|----------|----------|
| doubao-seed-2.0-code | | 见下 ↓ | 见下 ↓ |
| doubao-seed-2.0-pro | | | |
| doubao-seed-2.0-lite | | | |
| doubao-seed-code | | | |
| minimax-m2.7 | | | |
| minimax-m3 | | | |
| glm-4.7 | | | |
| deepseek-v4-flash | | | |
| deepseek-v4-pro | | | |
| kimi-k2.6 | | | |
| kimi-k2.7-code | | | |

---

## 已记录条目（2026-06-24）

### doubao-seed-2.0-code · T063_048（hard）— **006/011 复测 · turn 2 口语跳过**

| 字段 | 值 |
|------|-----|
| session | `704d8fc8…` / `8cffdb25…` |
| deviceId | `dev-mp9yxug4-2o4gh5ea` |
| 前端 bundle | `index-BDuoZAjL.js`（006 §11 已部署） |
| turn 1 | ✅ A 阶段 intake 正常 |
| turn 2 用户 | 口语跳过「就我们老两口。想看博物馆…」 |
| **ui** | **`OK`** — 问卷置灰常驻、跳过声明泡展示（006/011 修复生效） |
| **phase_route** | **`SKIP-DECL-ONLY` + `NO-TOOL`** — Agent 只输出声明泡后 **stopReason=stop 结束 run**，jsonl **无 tool_calls**；Harness **stage=planning、slots.ready=true**（**非 Harness 拦截**） |
| 方案 | ❌ 无（用户感知「卡在查天气」） |
| reward | **partial / 低** — A+UI 通过；B 未交付方案；rubric 计 `NO-TOOL` |
| 根因归类 | **模型/Agent 执行**（doubao-seed-2.0-code）：thinking 里计划调工具，但同轮仅 text 输出即结束；**非**前端、**非** Harness、**非** Gateway 宕机 |
| 备注 | eval `tool_progress: 查询天气` 为进展条误触（文案含「查天气」），轨迹无真实 `get_weather`；可再发一句「继续出完整方案」触发新 run |

### doubao-seed-2.0-code · T063_048（hard）— **旧测 · 部分完成 / 需重测**（007 前）

| 字段 | 值 |
|------|-----|
| session | `e6deb95a…` |
| deviceId | `dev-mp9yxug4-2o4gh5ea` |
| 首版方案 | ✅ 有（但 POI 偏商场，未满足博物馆/公园/面食） |
| 第 2 轮用户 | 「就我们老两口。想看博物馆，再逛逛公园。吃饭吃面食，清淡的。」 |
| **phase_route** | **`RE-INTAKE`** — 应为大阶段二模式②改方案，Agent 又出 intake |
| **ui** | **`UI-INTAKE`** — intakeLocked，新选择题不可展示（闪没） |
| reward | _待 score_from_logs（首版方案可计 partial）_ |
| 备注 | 007 前会话；UI/Agent 均已更新，**以上方 704d8fc8 复测为准** |

### doubao-seed-2.0-code · T063_034（medium）— **进行中**

| 字段 | 值 |
|------|-----|
| session | `ca691d88…` |
| 首版方案 | ✅ 有 link + 工具 |
| 追问「创意菜、不吃甜…」 | **phase_route: `NO-TOOL` + `NO-LINK`** — 未 search_places，仅文字改餐厅 |
| 追问「查天气、路线别太折腾…」 | **phase_route: `NO-TOOL` + `NO-LINK`** — 几乎无工具，全表重写无 link |
| reward | _待完整 4 轮后跑分_ |
| 备注 | 007 已部署；追问轮待 **复测** amap link / search_places |

---

## 待办

- [x] 007 已实施并部署 ECS（2026-06-24）
- [ ] 007 落地后：doubao T063_048 / T063_034 **复测**
- [ ] doubao T063_034 跑完 4 轮 + `score_from_logs --date 2026-06-24`
- [ ] 其余 10 模型 × 3 task 填表
