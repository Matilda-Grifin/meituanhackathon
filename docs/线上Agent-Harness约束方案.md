# 线上 Agent Harness 约束方案（本项目落地指南）

> 目标：在现有 OpenClaw + SOUL/Skill 架构上，补上 **YAML 显式能力边界**、**运行时自动验证**、**输出自动修复**，把测评里「事后打分」的规则前移到线上，减少模型跑偏对用户可见的影响。  
> 读者：自己迭代 / 答辩 / 简历补充设计思路时用。不要求一次全做，可按 P0→P1→P2 分期。

---

## 1. 先对齐：Harness 在本项目里指什么

业界说的 Harness Engineering，本质是 **在 Agent 循环外包一层「规则 + 校验 + 修复」**，不替代大模型决策，但限制「能做什么、做错了怎么办」。

| 能力 | 医疗类 Agent 常见做法 | **本项目的对应物** |
|------|----------------------|---------------------|
| YAML 能力边界 | 禁止诊断、禁止开药 | 补槽阶段禁止搜点/算路；工具白名单；行程阶段工具预算 |
| 运行时验证 | 输出含高危词 → 拦截 | 未确认人数却写「4人局」；工具失败却编造店名/气温；mock 口碑当真实点评 |
| 输出自动修复 | 补免责声明、就医警告 | 补「演示/mock 说明」「无实时数据」「预算为估算」「请自行预约」等 |

**和你们现状的关系：**

- **已有**：SOUL/Skill（软约束）、openclaw 工具 deny/allow、MCP 结构化错误返回、`测试/rubric.json` + `tool_schemas.json`（**事后**校验）。
- **缺少**：线上 **运行时** 读规则 → 拦工具 / 改文案；规则与测评 **同一套 YAML**，避免「测评严、线上松」。

---

## 2. 推荐总体架构（侧车 Harness，不改动 OpenClaw 内核）

OpenClaw 负责 ReAct 循环；Harness 作为 **侧车（Sidecar）** 挂在三条链路上：

```
用户消息
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  OpenClaw Gateway（LLM Think → Act → Observe）           │
│                                                          │
│  ① 调工具前 ──► Harness Pre-Tool（能否调、参数是否合法） │
│  ② 工具返回后 ──► Harness Post-Tool（记轨迹、更新状态）   │
│  ③ 最终回复前 ──► Harness Post-Output（校验 + 自动修复）  │
└─────────────────────────────────────────────────────────┘
   │
   ▼
用户看到的 Markdown（gateway-chat-ui）
```

**为什么用侧车而不是只靠 SOUL：**

- SOUL 是「希望模型遵守」；Harness 是「模型没遵守时系统兜底」。
- 测评 `rubric.json` 里已有 `no_search_route_before_intake` 等规则，适合 **升格为 YAML 策略** 在线上执行。

**落点建议（按改造成本从低到高）：**

| 优先级 | 挂载点 | 能做什么 |
|--------|--------|----------|
| P0 | **MCP 包装层**（`run_mcp.py` 或网关前代理） | 调工具前拦截、参数校验、工具次数计数 |
| P0 | **会话状态文件**（按 `sessionKey`） | 记录阶段 A/B、已调工具、槽位是否齐 |
| P1 | **输出后处理服务**（新建 `lifecare/harness/output_guard.py`，网关或 UI 前调用） | 检测违规文案 → 追加免责声明 / 触发重写 |
| P2 | **OpenClaw 插件/钩子**（若版本支持） | 流式过程中实时校验 |

---

## 3. YAML 策略文件：显式定义能力边界

建议新增目录：

```
meituan-lifecare-agent/
  lifecare/harness/
    policy.yaml          # 主策略（阶段、工具、预算、输出规则）
    repairs.yaml         # 自动修复模板
    session_state.py     # 读写会话状态
    pre_tool.py          # 调工具前校验
    post_output.py       # 回复后校验与修复
```

### 3.1 `policy.yaml` 结构示例（易懂版）

下面用**注释说明含义**，实际文件去掉行内中文注释即可。

```yaml
version: 1
domain: lifecare_travel

# ---------- 对话阶段（与 SOUL 大阶段一/二、A/B 对齐）----------
stages:
  intake:          # 阶段 A：补槽
    allow_tools: []   # 不允许任何 lifecare 搜点/算路
    deny_tools:
      - lifecare_search_places
      - lifecare_plan_route
    required_output:
      - intake_questions   # 须含 A/B/C/D 选择题

  planning:        # 阶段 B：出方案
    allow_tools:
      - lifecare_get_weather
      - lifecare_search_places
      - lifecare_plan_route
    optional_tools:      # 演示用沙盒
      - lifecare_get_venue_queue
      - lifecare_get_attraction_crowd

  followup_qa:     # 大阶段二 · 只问答
    allow_tools: []      # 默认不调工具，除非用户明确改方案

  followup_replan: # 大阶段二 · 改方案
    allow_tools:
      - lifecare_get_weather
      - lifecare_search_places
      - lifecare_plan_route

# ---------- 工具预算（与测评 task_metrics 公式一致，便于线上线下统一）----------
tool_budget:
  base_total: 12
  per_extra_day: 6
  caps:
    search_places: "min(4 * trip_days, 12)"
    get_weather: "min(2 * trip_days, 6)"
    plan_route: "trip_days * (anchors_per_day - 1) + 2"  # 半天游另 cap=3

# ---------- 槽位与上下文条件（决定当前 stage）----------
context_rules:
  - id: slots_incomplete
    when: "not slots.ready"
    force_stage: intake

  - id: planning_ready
    when: "slots.ready and not session.has_full_plan"
    force_stage: planning

  - id: has_plan_and_user_asks_detail
    when: "session.has_full_plan and user.intent == qa"
    force_stage: followup_qa

# ---------- 输出禁止项（运行时扫描助手最终文本）----------
output_forbidden:
  - id: no_preset_party_size
    when: "not slots.party_size"
    patterns: ["\\d+人", "两大一小", "我们\\d+个"]
    severity: error          # error=必须修复；warn=只打日志

  - id: no_fake_realtime_after_tool_fail
    when: "session.tools_degraded"
    patterns: ["驾车约\\d+分钟", "气温\\d+°", "评分\\d\\.\\d"]
    severity: error

  - id: no_claim_real_dianping_volume
    when: "output.mentions_reviews"
    patterns: ["\\d+条评价", "真实点评", "美团评论"]
    unless_contains: ["演示", "mock", "代理"]
    severity: warn

# ---------- 输出必选项（缺了则自动补）----------
output_required:
  - id: mock_disclaimer
    when: "output.uses_mock_reputation or output.cites_seed_reviews"
    insert: "footer"   # 文末追加
    template_id: mock_data_notice

  - id: budget_estimate_notice
    when: "output.has_budget_table"
    insert: "after_budget_table"
    template_id: budget_estimate_notice

  - id: tool_degraded_notice
    when: "session.tools_degraded"
    insert: "top"      # 文首醒目提示
    template_id: no_realtime_data_notice
```

### 3.2 `repairs.yaml`：自动修复模板

```yaml
templates:
  mock_data_notice: |
    > **说明**：文中涉及的用户偏好/部分口碑描述来自演示种子或合成字段，POI 名称与坐标以高德为准，不代表真实点评库条数。

  budget_estimate_notice: |
    > **说明**：预算为根据公开票价与人均消费的估算区间，实际以到店/购票为准。

  no_realtime_data_notice: |
    > **提示**：当前实时地图/天气工具暂不可用，以下建议未基于最新查询结果，店名、路程与气温请勿当作实时数据。

  booking_reminder: |
    > **预约**：热门场馆/餐厅建议提前在官方小程序预约。

rules:
  - match: "output_forbidden.no_preset_party_size"
    action: strip_and_append
    strip_patterns: ["\\d+人朋友局", "为您安排\\d+人"]
    append_template: null
    fallback: regenerate_with_hint   # 可选：带 hint 让模型重写一句

  - match: "output_required.mock_disclaimer"
    action: append_if_missing
    template_id: mock_data_notice

  - match: "output_required.tool_degraded_notice"
    action: prepend_if_missing
    template_id: no_realtime_data_notice
```

### 3.3 和现有文件的关系

| 现有文件 | Harness 中怎么用 |
|----------|------------------|
| `测试/rubric.json` | **迁移**：`rules[]` → `policy.yaml` 的 `output_forbidden` / `context_rules`；测评与线上共用同一 YAML |
| `测试/tool_schemas.json` | **复用**：Pre-Tool 参数校验（city 必填、limit 范围等） |
| `workspace/SOUL.md` | **保留**：人设与产品话术；YAML 管「硬边界」，SOUL 管「怎么说」 |
| `workspace/skills/*` | **保留**：步骤说明；YAML 的 `stages` 与 skill 名称做映射表 |

---

## 4. 运行时自动验证：三条链路怎么做

### 4.1 调工具前（Pre-Tool）——最重要

**时机**：OpenClaw 即将调用 `lifecare__*` 之前（在 MCP 入口或网关 tool 代理处）。

**输入**：

- 当前 `sessionKey`
- 工具名 + 参数
- 会话状态（阶段、已调工具次数、槽位是否齐、本轮是否工具降级）

**逻辑（按顺序）**：

1. 读 `policy.yaml`，解析当前 `stage`（见 §5 状态机）。
2. 若工具在 `deny_tools` → **拒绝调用**，返回结构化 JSON（与现有沙盒错误风格一致），让模型改用「先补槽」话术，而不是抛异常。
3. 若工具不在 `allow_tools` → 拒绝。
4. 校验参数（复用 `tool_schema_validate` 逻辑）。
5. 校验工具预算（`search`/`route`/`weather` 是否超限）→ 超限则拒绝并 hint「请基于已有 POI 排表」。

**返回给模型的示例（用户不可见，仅 tool 结果）**：

```json
{
  "ok": false,
  "error": "harness_blocked",
  "rule_id": "no_search_route_before_intake",
  "hint_zh": "槽位未齐，请先完成 travel-intake 选择题，本回合禁止搜点。"
}
```

这样和现有 MCP「不抛异常、只返 JSON」一致，Agent 循环不会白挂。

### 4.2 工具返回后（Post-Tool）——记状态

**时机**：每次工具成功/失败后。

**更新会话状态**（建议存 `~/.openclaw/harness_state/{sessionKey}.json`）：

- `tools_called[]`：工具名、时间、ok/error
- `tools_degraded`：连续失败或 Key 无效则为 true
- `trip_days_D`、`anchors_per_day`：从槽位或用户话解析，供预算用
- `has_full_plan`：检测到输出含「行程速览表」等标记时置 true

### 4.3 最终回复前（Post-Output）——校验 + 修复

**时机**：助手一条完整回复生成完毕、推给用户之前。

**方式二选一（建议先做 A，再做 B）：**

| 方式 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| A. 规则引擎 | 正则/关键词扫 `policy.yaml` 的 `output_forbidden` / `output_required` | 快、可解释、无额外 LLM 成本 | 复杂语义难覆盖 |
| B. 小模型裁判 | 用便宜 LLM + 短 prompt 判 PASS/FAIL | 覆盖口语变体 | 延迟与成本 |

**本项目建议：A 为主，B 只用于 `regenerate_with_hint` 的少数 hard case。**

**校验项（与赛题/测评对齐）**：

- 用户未说人数 → 正文不得出现确定人数
- 工具降级 → 不得出现精确车程/气温/评分
- 引用 mock 口碑 → 须有「演示/mock」类说明
- 有预算表 → 须有「估算」说明
- 补槽阶段 → 不得输出完整行程表（可选：直接截断并提示）

---

## 5. 会话状态机：Harness 怎么知道「现在该哪个阶段」

仅靠 SOUL 文字不够；Harness 需要 **可计算的 session state**：

```
                    用户说要规划
                         │
                         ▼
                  ┌─────────────┐
         ┌───────│   intake    │ 槽位不齐
         │       └──────┬──────┘
         │              │ 选择题答完 / 用户说「全部默认」
         │              ▼
         │       ┌─────────────┐
         │       │  planning   │ 调工具、出完整方案
         │       └──────┬──────┘
         │              │ 检测到 has_full_plan
         │              ▼
         │       ┌─────────────┐
         └──────►│  followup   │──► followup_qa / followup_replan
                 └─────────────┘
```

**槽位 `slots.ready` 怎么判：**

- 优先：用户通过前端提交的「选择题答案：第1题选A…」解析
- 其次：用户自然语言里已包含 city、时段、人数等（可复用 `travel-intake` 关键词表，写进 `session_state.py`）
- 与 SOUL 一致：**MEMORY.md 里的人设不能自动填人数**

**`has_full_plan` 怎么判：**

- 助手文本含 `## 行程速览` 或表格头 `时段 | 做什么` 等（规则见 `local-itinerary-planner`）
- 或由模型在方案末尾输出隐藏标记 `<!-- plan_complete -->`（可选，便于 Harness 识别）

---

## 6. 输出自动修复：具体修什么、怎么修

### 6.1 修复动作类型

| 动作 | 含义 | 本项目示例 |
|------|------|------------|
| `append_if_missing` | 缺免责声明则在文末补一段 | mock 口碑、预算估算 |
| `prepend_if_missing` | 文首加醒目提示 | 工具不可用 |
| `strip_and_append` | 删掉违规句，必要时补一句 | 未确认人数却写「4人局」 |
| `block_and_regenerate` | 整段不合格，带 rule_id 让模型重写 | 严重编造实时数据 |
| `log_only` | 只记 harness 日志，不改用户可见文案 | 低风险 warn |

### 6.2 本项目优先做的 5 条修复（P0）

1. **工具降级文首提示**（`tool_degraded_notice`）—— 对齐 SOUL「须先说明无实时数据」。
2. **Mock 口碑文末说明**（`mock_data_notice`）—— 对齐 `mock-user-prefs-reviews` skill。
3. **预算表后估算说明**（`budget_estimate_notice`）。
4. **未确认人数检测到「N人」** → strip 或触发重写（对齐 `no_preset_party_size`）。
5. **热门景点段落后预约提醒**（`booking_reminder`）—— 产品价值高、误伤低。

### 6.3 不建议自动修的（避免越修越乱）

- 完整行程表的 POI 顺序（应靠 replan，不要正则改表）
- Mermaid 语法错误（交给前端渲染兜底）
- 用户明确要求的创意文案

### 6.4 用户看到修复吗

- **轻量修复**（文末一句说明）：用户只觉得 Agent 更严谨。
- **重修复**（删句/重写）：可在开发模式打 `harness_repair_log`；生产环境默认静默。

---

## 7. 与 gateway-chat-ui / 测评的衔接

### 7.1 前端

- 流式结束后，可对 `assistant_text` 调一次 Harness API：`POST /api/harness/validate-and-repair`。
- 返回 `{ text, repairs_applied[], blocked: false }` 再渲染气泡。
- **不要**只在浏览器里修：否则 CLI / 其他渠道无保障；逻辑放服务端。

### 7.2 测评闭环

- 批跑 `collect_openclaw_pred.py` 时同样走 Harness → `rules_applied` 与 YAML `rule_id` 一致。
- 报表多一列：`harness_blocked_tools`、`harness_repairs`，便于看「若上线 Harness 能拦多少坏 case」。

### 7.3 日志

建议 `benchmark/results/harness_events.jsonl`：

```json
{
  "ts": "2026-06-05T12:00:00Z",
  "session_id": "...",
  "phase": "pre_tool",
  "rule_id": "no_search_route_before_intake",
  "action": "blocked",
  "tool": "lifecare_search_places"
}
```

---

## 8. 分期实施建议

### P0（1～2 天，性价比最高）

- [ ] 新增 `policy.yaml` + `repairs.yaml`（先从 `rubric.json` 迁 3 条规则）
- [ ] `session_state.py`：sessionKey → stage + tools_called
- [ ] `run_mcp.py` 入口 Pre-Tool：**仅拦 intake 阶段 search/route**
- [ ] Post-Output：**tool_degraded + mock_disclaimer** 两段 append

### P1（3～5 天）

- [ ] 工具预算与 `task_metrics` 公式统一
- [ ] `gateway_context_api` 或独立 FastAPI 暴露 `/api/harness/*`
- [ ] gateway-chat-ui 流式结束后调用修复 API
- [ ] 测评脚本共用 Harness，出对比报告

### P2（可选，偏工程化）

- [ ] 槽位解析与 `travel-intake` 结构化对齐（减少误判 stage）
- [ ] 流式中间态校验（长方案生成过程中提前发现编造）
- [ ] 餐饮 filter tool 上线后，YAML 增加 `get_review_snippets` / `filter_dining` 阶段规则

---

## 9. 答辩 / 简历可怎么说

**现状（诚实）：**  
约束主要靠 SOUL/Skill 与 openclaw 工具白名单；测评侧有事後 rubric 与 schema 校验，**线上尚无独立 Harness**。

**若按本方案落地后可说：**  
在 OpenClaw ReAct 循环外增加 **YAML 策略侧车**，实现调工具前拦截、回复后校验与免责声明自动补齐，并与测评规则共用同一套 policy，形成「线上护栏 + 离线打分」一致的质量闭环。

**不要写：** Mem0、熵压缩、就医警告（与本项目无关）。  
**要写：** 补槽阶段禁搜点、mock 数据声明、工具降级提示、人数幻觉拦截、工具预算——这些都是赛题真实痛点。

---

## 10. 常见问题

**Q：有了 Harness，SOUL 还要吗？**  
要。SOUL 管语气、表格格式、Mermaid；Harness 管「绝不能做什么」。两者互补。

**Q：会不会和 OpenClaw 内置逻辑冲突？**  
Pre-Tool 在 MCP 层拒绝时，返回与现有 `ok: false` JSON 一致即可；不要抛未捕获异常。

**Q：模型被拦了会不会更笨？**  
hint_zh 要写清「下一步该做什么」（例如先出选择题），和 SOUL 阶段 A 话术一致，模型通常能自我纠正。

**Q：YAML 谁维护？**  
产品改流程 → 改 `policy.yaml` 的 `stages`；测评改 rubric → 同步改 `output_forbidden`；避免 SOUL 与 YAML 两套真相。

---

## 11. 相关现有文件索引

| 路径 | 作用 |
|------|------|
| `workspace/SOUL.md` | 阶段 A/B、大阶段二路由（软约束） |
| `workspace/skills/travel-intake/SKILL.md` | 补槽规则 |
| `测试/rubric.json` | 可迁移到 YAML 的评测量表 |
| `测试/tool_schemas.json` | Pre-Tool 参数校验 |
| `测试/task_metrics.py` | 工具预算公式来源 |
| `run_mcp.py` | Pre-Tool 首选挂载点 |
| `gateway_context_api.py` | 可扩展 Harness HTTP API |
| `docs/AGENT_EVAL_PLAN.md` | 记忆/trace 规划（与 Harness 日志可合并） |

---

---

## 12. 已落地（2026-06-05）

| 组件 | 路径 |
|------|------|
| Harness 核心 | `lifecare/harness/` |
| MCP Pre/Post-Tool | `run_mcp.py` + `lifecare/harness/mcp_wrapper.py` |
| HTTP API | `gateway_context_api.py` → `/api/harness/*` |
| 前端（非阻塞） | `gateway-chat-ui/src/harnessClient.ts` + `App.tsx` |
| 测评 | `测试/harness_eval.py` → `rubric_engine` 的 `harness` 字段 |
| 线上备份 | `scripts/ecs_backup_online.py` → `/root/backups/lifecare-online-*.tar.gz` |
| 部署 | `scripts/ecs_deploy_harness.py` |
| 冒烟 | `scripts/ecs_smoke_harness.py`、`lifecare/harness/test_harness.py` |

**线上备份位置（ECS）：** `/root/backups/lifecare-online-20260605-041416.tar.gz`（含仓库、openclaw.json、workspace、sessions）

**回滚：** 解压备份后按包内 `RESTORE.md` 操作，或运行备份时生成的 workspace.bak-* 目录。

---

*文档版本：2026-06-05 · 对应仓库 meituan-lifecare-agent 线上架构*
