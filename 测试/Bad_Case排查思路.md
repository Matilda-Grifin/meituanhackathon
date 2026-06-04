# Lifecare Agent Bad Case 排查思路

本文档把通用 Agent Bad Case 分类与「五步溯源法」**落地到本仓库**（`meituan-lifecare-agent` + `测试/` 评测管线）。  
与 [`指标.md`](./指标.md)、[`指标对照与落地说明.md`](./指标对照与落地说明.md)、[`rubric.json`](./rubric.json) 配套使用。

---

## 一、如何定义本项目的 Bad Case？

在 Agent 领域，Bad Case = **考卷/规则定义的「预期行为」** 与 **一次真实运行（pred + 工具日志）的「实际表现」** 之间的差距。  
本赛题里「预期」来自：`cases.json` 的 `user_text` / `eval` / `simulation`，加上 `rubric.json`、`task_metrics`、`SOUL.md` / `travel-intake`。

建议按下面四类打标签（可并存），便于统计与答辩：

### 1. 意图识别错误（Intent Mismatch）

**定义：** 用户意图与 Agent 进入的任务类型不一致。

| 通用例子 | 本赛题等价 |
|----------|------------|
| 想订票，Agent 写诗 | 用户要**纯天气**，Agent 出了一整份多日行程 |
| 想改期，Agent 直接退票 | 用户要**规划**，Agent 只做 intake 不进入 B 阶段调工具 |
| 非法/有害请求 | 用户要钓鱼网站，Agent 仍输出 POI 行程（case **20**） |

**本项目怎么判：**

- `rubric_context.infer_context()` → `planning_intent` / `weather_primary` / `slots_incomplete` / `abuse` 等 flags（见 `agent_eval` 每条结果的 `context`）。
- 特殊题走 `task_metrics.compute_special_case()`，**不**用规划完整度（如拒答、降级、冲突、重规划、预算）。

**常见信号：**

- `failures` 含 `weather_must_call_tool` 但用户其实在要规划；
- `task_success_scope` 与 case 设计不符（如非法题却 `planning`）；
- `failure_hints` 含 `first_turn_skipped_intake_or_direct_plan`（槽位未齐却直接给长方案）。

---

### 2. 轨迹失效（Trajectory Failure）

**定义：** 多轮对话 + 工具调用链路上出现异常，导致任务完不成或评测采偏。

| 子类 | 本赛题表现 | 排查入口 |
|------|------------|----------|
| **死循环 / 狂调** | 同一工具连续 ≥3 次无进展 | `pred.tools_in_order`；`process_metrics.detect_retry_exceeded` |
| **工具幻觉** | 调用未注册的 `lifecare_*` 或 `web_search` 绕路 | `turns[].tools`；OpenClaw 日志 |
| **参数错误** | Schema 不合规（缺 `keywords`、城市为空等） | `tool_schema_validate.py` + `turns[].tool_calls[].arguments` |
| **采集轨迹断档** | 模拟用户第二句**从未发出** | `simulation_audit.jsonl` vs `cases.json` 的 `after_assistant_turn` |

**本项目工具白名单（规划主链）：**

- `lifecare_get_weather` / `lifecare_search_places` / `lifecare_plan_route`（网关侧常带前缀 `lifecare__`）

**动线预算（也算轨迹类 Bad Case）：**

- `plan_route` 次数 > `max_plan_route(D,A)` 或总工具数 > `M(D)` → `task_metrics.reasons_fail` 含 `plan_route_count>` / `tools_total>`。

---

### 3. 约束违背（Constraint Violation）

**定义：** 违反 System Prompt、Skill、Rubric 或 case 级 `eval` 约束。

| 约束来源 | 例子 |
|----------|------|
| **SOUL / travel-intake** | 槽位未齐却先 `search`/`route`；未出 A/B/C 选择题 |
| **rubric.json** | `no_search_route_before_intake`、`no_preset_party_size` |
| **case.eval** | 预算 8000 却无任何分天费用（case **24**）；改室内后仍大段户外（case **23**） |
| **用户事实** | 用户未说 4 人，回复却写死「4 人」 |

**本项目怎么判：**

- 规则分：`rubric_engine` → `rules_applied` / `failures`；
- 北极星：`task_success` + `reasons_fail`（见 `task_metrics.py`）；
- 六维：`dimension_scores`（`pass` 仅看 `total_score ≥ 60`，与 `task_success` 可分离）。

---

### 4. 性能与安全性（Performance & Safety）

**定义：** 时效、安全、合规类问题。

| 子类 | 本赛题口径 |
|------|------------|
| **响应过慢** | 首响 A 阶段目标 **10s** 可见 intake（`intake_within_10s`，需 pred 带 `time_to_first_*`）；全任务 `elapsed_s` / P95 > 120s → `budget_sla_pass: false` |
| **安全/非法** | case **20**：须拒答、不出行程表 |
| **工具降级未告知** | case **21**：MCP/高德不可用须说明，禁止编造实时 POI（须采集时无效 Key 或关 MCP） |
| **Prompt 泄露** | 回复出现完整 system 指令（一般人工抽检） |

**日志：**

- Agent 侧：`collect_openclaw_pred` → `results/agent_pred_*.jsonl`
- MCP 侧：`results/mcp_tool_calls.jsonl`（`LIFECARE_MCP_TOOL_LOG`）

---

### 5. 评测/环境假 Bad Case（务必单独标记）

以下情况 **不是模型能力问题**，但会在榜单上显示为失败，排查时必须先剔除：

| 现象 | 根因 | 处理 |
|------|------|------|
| case **21** 在 ECS 上「降级题」却 task_success 失败 | 环境 MCP 正常，Agent 合理调工具 | 采集时 `collect_amap_key_override: INVALID_FOR_EVAL` |
| case **23** 从未收到「改室内」用户句 | `after_assistant_turn: 3` 但实际只跑 2 轮助手 | 改为 `after_assistant_turn: 2` |
| `missing_pred` | pred 的 `case_id` 与考卷数字 id 不一致 | 重采或对齐 `agent_pred_live.jsonl` |
| `pass=true` 但 `task_success=false` | 设计如此：六维及格 ≠ 北极星 | 答辩时分开报 |

---

## 二、排查思路：五步溯源法（本项目版）

当一个 Bad Case 出现时，按 **Agent 决策链从外到内、再从内到外** 交叉验证。  
推荐顺序：**环境 → 工具 → 轨迹/采集 → 提示词/考卷 → 模型**，并同步打开同一次运行的 `agent_eval` + `case_scorecard` + `simulation_audit`。

```text
用户 case
  → OpenClaw Gateway（豆包等）
    → workspace: SOUL / skills / MEMORY
      → MCP: run_mcp.py（高德/天气）
        → pred.jsonl + mcp_tool_calls.jsonl
          → rubric_engine + task_metrics → agent_eval JSON
```

---

### 第一步：环境检查（Environment / Data Observation）

**排查点：** 工具返回的数据对吗？采集条件是否与考卷场景一致？

| 检查项 | 怎么做 |
|--------|--------|
| MCP 是否成功 | 读 `results/mcp_tool_calls.jsonl` 对应 session 时段的 `ok`、`error`、`duration_ms` |
| 高德 Key | ECS `~/.openclaw/openclaw.json` → `mcp.servers.lifecare.env.AMAP_KEY`；case 21 是否应无效 Key |
| 网关/MCP 是否装入 | Agent 正文是否出现「未装入 MCP」；工具列表是否为空 |
| 采集是否完整 | `pred` 是否有 `turns`、`tools_in_order`；`case_id` 是否为数字 1–26 |

**结论模板：**

- 若 API 返回空/错/Key 无效 → **GIGO**，先修环境或采集脚本，再评 Agent。
- 若考卷要「降级」但环境「全绿」→ 标为 **环境假 Bad Case**，不要直接结论「模型不会降级」。

**本仓库案例（case 21）：**  
首轮在 ECS 上 MCP 正常 → Agent 输出带高德评分的完整方案 → `tool_degrade_ack_missing`。对策：采集前临时改无效 `AMAP_KEY`（`collect_openclaw_pred._set_lifecare_amap_key`）。

---

### 第二步：工具调用层检查（Action / Tool Call）

**排查点：** Agent 发出的工具调用是否正确？

| 问题 | 分析方向 | 本项目对应 |
|------|----------|------------|
| **选错工具** | 意图路由弱 | 该天气却狂 `search`；该规划却零工具 → `tools_vs_framework.roles_miss` |
| **参数错** | Tool Description / Schema 不清 | `tool_schema_validate.validate_pred_tool_calls` |
| **抢跑工具** | 未 intake 先 search/route | `forbidden_tools_before_intake` / `no_search_route_before_intake` |
| **超预算** | 刷 route/search | `tool_budget` 字段：`plan_route_ok`、`tools_total_ok` |
| **重试过多** | 同工具连续调用 | `retry_exceeded`（`process_metrics`） |

**建议命令：**

```powershell
# 单条 pred 看工具序
python run_agent_eval.py --pred results/agent_pred_live.jsonl --only 22

# 全量 evaluator（含模拟一致性）
python run_evaluator.py --pred results/agent_pred_live.jsonl --audit results/simulation_audit.jsonl
```

**日志字段：**

- `pred.tools_in_order`：按次记录（用于预算与重试）
- `pred.turns[].tool_calls[]`：name / arguments / ok / error（依赖 OpenClaw `--json` 是否吐出）

---

### 第三步：推理与规划层检查（Thought / Planning）

**排查点：** 多轮逻辑是否合理？（本仓库 **通常无 Thought 明文**，用轨迹 + 正文间接推断。）

| 检查项 | 怎么看 |
|--------|--------|
| 逻辑矛盾 | 用户要 14:00 上车，方案写 14:30 离站却称「无时间压力」→ case **22** |
| 改主意未重规划 | 用户已说「改室内」，最终仍西湖散步且无工具 → case **23** |
| 规划结构 | `plan_structure_score`、正文是否含「第 N 天 / 时段表」 |
| 证据接地 | `evidence_grounding_pct`：有 weather/search 时正文是否出现天气/POI/路线类表述 |

**若 OpenClaw 导出 reasoning：** 可对接 `process_metrics` P2；当前 pred **无** Thought 字段时，以 `assistant_text` + `user_messages` 对齐推理。

**本仓库案例（case 22）：**  
Agent 用「改时刻」消化冲突但未说「冲突」→ 属推理/表述层；评测侧用 `task_metrics` 扩展规则：离站 ≥14:30 且去东站 → 视为已处理冲突（答辩需说明口径）。

**本仓库案例（case 23）：**  
根因往往在 **采集层**：`after_assistant_turn` 与真实轮次不一致 → 推理层根本没收到改室内输入。

---

### 第四步：提示词层检查（System Prompt / Context）

**排查点：** 指令是否歧义、冲突或遗忘？

| 文件 | 作用 |
|------|------|
| `workspace/SOUL.md` | 首响 A/B/C、工具不可用、时间冲突、改主意重规划 |
| `workspace/skills/travel-intake/SKILL.md` | 槽位与选择题 |
| `workspace/skills/local-itinerary-planner/SKILL.md` | 完整方案结构 |
| `workspace/MEMORY.md` | 演示人设（勿当成用户已确认人数/城市） |
| `cases.json` → `simulation` | 多轮用户脚本是否与轮次对齐 |

**常见冲突：**

- SOUL 要求「槽位未齐先选择题」 vs 用户一句带齐槽位 → Agent 跳过 intake（`failure_hints`）；
- SOUL 要求「B 阶段先一句进展再并行工具」 vs 模型一上来就调工具（首响维度降分）；
- 长对话后预算约束被遗忘（本考卷多为 1–3 轮，较少见）。

**改法：** 先改 SOUL/Skill → 同步 ECS `~/.openclaw/workspace/` → 再 `collect_openclaw_pred` 重采。

---

### 第五步：模型底层检查（Base Model）

**排查点：** Prompt、数据、考卷均合理，简单逻辑仍稳定翻车？

| 现象 | 可能原因 |
|------|----------|
| 反复违反 intake | 模型过小或 compaction 丢上下文 |
| 中文地点/时段理解错 | 换更强主模型（`openclaw.json` → `agents.defaults.model`） |
| 工具结果明明正确仍胡编 | 需 `run_deepeval_judge.py` 抽检或换模型 |

**本项目当前：** 网关侧多为火山/豆包类；若仅换模型即可修复且前几步均正常，才归因为 **Base Model**。

---

## 三、与本项目评测字段的对照表

| 五步 | 优先看的产物 |
|------|----------------|
| 环境 | `mcp_tool_calls.jsonl`、`openclaw.json` MCP 配置、case `eval.collect_amap_key_override` |
| 工具 | `tools_in_order`、`tool_budget`、`tool_schema`、`rules_applied` |
| 推理/规划 | `assistant_text`、`user_messages`、`simulation_audit.jsonl`、`process_metrics` |
| 提示词 | `SOUL.md`、skills、`failure_hints` |
| 模型 | 同 case 换模型 A/B 复采 |

**一键产出（答辩用）：**

```text
collect_openclaw_pred.py  →  agent_pred_*.jsonl + simulation_audit.jsonl
run_agent_eval.py         →  agent_eval_*.json（含 task_success、dimension_scores、process_metrics_summary）
run_evaluator.py          →  evaluator_report.json（失败归因 + 模拟一致性）
build_case_scorecard.py   →  case_scorecard.json（延迟、轮次、工具）
```

---

## 四、已验证的 Hard/Medium 修复范例（21–23）

以下记入「Bad Case 台账」，说明 **类型 + 溯源结论 + 改法**：

| Case | Bad Case 类型 | 五步结论 | 处理 |
|------|---------------|----------|------|
| **21** | 环境假失败 + 约束（降级） | ① 环境 MCP 正常；④ 考卷要降级 | 采集无效 `AMAP_KEY` + SOUL 降级话术 |
| **22** | 约束 + 推理表述 | ③ 改时刻但未说冲突；④ SOUL 补「先指出过紧」；评测认改时刻 | `task_metrics` 冲突启发式 |
| **23** | 轨迹/采集 | ② 多轮脚本未触发 | `after_assistant_turn` 3→2 + SOUL 改主意重调工具 |

重跑后（ECS）：`task_success` **21/22/23 均为 true**（pred：`results/agent_pred_rerun_21_23.jsonl`）。

---

## 五、Bad Case 记录模板（建议每条失败 case 填一行）

```markdown
### Case ID: __

- **预期（考卷）**：
- **实际（pred 摘要）**：
- **分类**：□ 意图 □ 轨迹 □ 约束 □ 性能/安全 □ 评测/环境假
- **五步结论**：①环境 ②工具 ③推理 ④提示词 ⑤模型
- **根因一句话**：
- **改法**：□ 改考卷 □ 改采集 □ 改 SOUL □ 改 rubric/task_metrics □ 改模型/网关
- **复测命令**：
- **复测结果**：task_success=  pass=  
```

---

## 六、相关文件索引

| 文件 | 作用 |
|------|------|
| [`eval_cases/dev/cases.json`](./eval_cases/dev/cases.json) | 考卷与 `eval` / `simulation` |
| [`collect_openclaw_pred.py`](./collect_openclaw_pred.py) | Live 采集 + AMAP Key 临时覆盖 |
| [`task_metrics.py`](./task_metrics.py) | `task_success`、特殊题、工具预算 |
| [`rubric_engine.py`](./rubric_engine.py) | 规则 + 六维加权 |
| [`process_metrics.py`](./process_metrics.py) | 过程指标、失败模式、P95 |
| [`run_evaluator.py`](./run_evaluator.py) | 汇总 + 模拟一致性 + 归因 |
| [`../workspace/SOUL.md`](../workspace/SOUL.md) | Agent 行为主约束 |

---

*文档版本：与 26 条 dev 考卷、ECS 重跑 21–23 实践同步；评测目录为 `测试/`。*
