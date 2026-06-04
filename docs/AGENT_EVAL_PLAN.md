# LifeCare Agent 测评方案（Agent Eval，非 LLM Benchmark）

> 适用对象：OpenClaw 网关 + lifecare MCP + workspace 记忆 + 多轮规划 的整条系统，不是单独测豆包/ GPT 分数。

---

## 1. 你在测什么

| 维度 | LLM Benchmark（MMLU 等） | 本项目的 Agent Eval |
|------|-------------------------|---------------------|
| 对象 | 模型权重/推理 | Planner、工具、记忆、编排、延迟 |
| 答案 | 多数有标准答案 | 约束满足 + 轨迹 + 人评 |
| 数据 | train/test split | 评测用例集（Eval Set） |
| 状态 | 无状态单轮为主 | 有状态、多轮、工具副作用 |

结论：不需要传统 ML 的 train/test 划分；需要 可重复的 benchmark suite + Dev/Hidden 两套集，防止「背评测集」。

---

## 2. 两层记忆评测（回答「是不是写死 memory？」）

### 2.1 Static Memory Eval（单元测试）

`benchmark/` 或 `travel_memory_eval_v1.json` 中手工注入片段：

```json
{
  "case_id": "tokyo_001",
  "memory_snippet": "用户偏好博物馆、预算偏低",
  "query": "东京周末怎么玩",
  "expected_constraints": ["museum", "budget_low"]
}
```

- 用途：调 prompt、调 allowlist、调工具顺序；稳定、可 diff。
- 不是最终目标；不代表 OpenClaw 真实流水线。

### 2.2 Full Pipeline Memory Eval（系统测，推荐主战场）

不要在 JSON 里写死 `"memory": "用户喜欢 museum"` 当唯一输入；而应：

1. 喂多轮历史（或脚本写入 `~/.openclaw/workspace/MEMORY.md` + 向量库，若已启用）。
2. 让 OpenClaw 自己 summarize → 存 md → retrieve → 注入 prompt。
3. 新 query：`帮我安排大阪周末`。
4. 断言：
   - Retrieval：是否召回 museum / 预算 / 慢节奏等；
   - 行为：最终 itinerary 是否体现，且无未确认人数（如用户只说「朋友」却出现 4 人）。

记录 Memory Trace（答辩/调试用）：

```json
{
  "retrieved_memories": [{"content": "...", "score": 0.82}],
  "compressed_memory": "...",
  "used_in_prompt": "...",
  "final_response": "..."
}
```

OpenClaw 的 `MEMORY.md`、session 历史、memory-core 插件属于生产记忆；Static JSON 只是对照组。

---

## 3. 推荐目录结构

```
benchmark/
  scenarios.json          # 已有：用户句 + 期望标签
  gold_trajectories.jsonl # 已有：工具序列 gold
  eval_cases/
    dev/                  # ~100 条，日常改 prompt 就看
    hidden/               # ~30 条，少看，防 overfit
  rubrics/
    constraint_check.md   # 餐饮+文娱、首 token、禁编造排队
  results/                # 每次 run 的 JSON + 报告
```

Dev / Hidden 分工：

- Dev：天天跑，改 SOUL、travel-intake、工具白名单。
- Hidden：发版前跑一遍，判断「真提升还是背题」。

---

## 4. Case Coverage（比 split 更重要）

| 类型 | 示例 |
|------|------|
| 槽位缺失 | 只说「跟朋友玩」→ 必须先问人数 |
| 人数自填 | 选 D +「5 人」 |
| 预算冲突 | 想省钱又要高端 |
| 时间冲突 | 今晚 + 闭馆 POI |
| 记忆矛盾 | MEMORY 写 4 人朋友局，本轮未确认不得用 |
| 工具失败 | lifecare not found / 高德空结果 |
| 天气 | 未来多天 vs 只返回今天 |
| 首 token SLA | 槽位不齐时禁止先调 MCP |
| 长上下文 | 多轮 intake 后再规划 |

本仓库 `benchmark/intent_heuristic.py`、`eval_tool_trajectory.py` 可扩展为 CI 门禁。

---

## 5. 自动化指标（分层）

| 层级 | 指标 | 实现建议 |
|------|------|----------|
| 效率 | 首 token、E2E、工具耗时 | `mcp_tool_calls.jsonl` + 网关日志 |
| 可靠性 | 工具成功率、空结果率 | 解析 trajectory |
| 约束 | 含餐饮+文娱、无编造排队 | 脚本扫输出 JSON/关键词 |
| 规划质量 | 绕路、总时长 vs 用户时长 | `plan_route` 相邻段 + 规则 |
| 记忆 | 约束是否来自 retrieval | LLM-as-judge + 人工 spot check |
| 稳定性 | 同 seed 两次 diff | 固定 temperature + mock 工具 |

北极星（选 1～2 个对外）：

1. 任务完成率：SLA 内满足硬约束且可执行动线。  
2. 首 Token / 首可用方案时间：对齐赛题 &lt;10s。

勿单盯完成率，须配套 约束检查 + 工具成功率。

---

## 6. 可重复环境

固定：

- `openclaw.json` 快照（或 docker compose）
- `forecast_days` / 高德 mock（`MOCK_SANDBOX_BASE_URL`）
- 模型与 `temperature`
- session seed

命令示例（本地/CI）：

```bash
python benchmark/run_intent_smoke.py
python benchmark/eval_tool_trajectory.py --cases benchmark/eval_cases/dev
```

网关对话回放：导出 `chat.history` → 转成 eval case。

---

## 7. 业界参考（建议阅读顺序）

### 7.1 Agent / Trace Eval（优先）

- [DeepEval – Agent Evaluation](https://docs.confident-ai.com/docs/agents-introduction)  
- [DeepEval – Agent Metrics](https://docs.confident-ai.com/docs/metrics-introduction)  
- [LangSmith – Evaluation](https://docs.smith.langchain.com/evaluation)  
- [LangSmith – Datasets & Testing](https://docs.smith.langchain.com/evaluation/how_to_guides)  
- [Braintrust – Evaluations](https://www.braintrust.dev/docs/guides/evals)  

### 7.2 本地 / CLI

- [Promptfoo](https://www.promptfoo.dev/docs/intro/) — prompt regression、YAML 用例  

### 7.3 学术 / 基准

- [AgentBench (GitHub)](https://github.com/THUDM/AgentBench)  
- [AgentBench 论文](https://arxiv.org/abs/2308.03688)  
- [G-Eval (LLM-as-Judge)](https://arxiv.org/abs/2303.16634)  

### 7.4 综述 / 实战

- 搜索：`agent evaluation trajectory`、`eval driven development agent`、`stateful agent evaluation`  
- Reddit / 社区常见结论：离线全过、线上仍炸 → 应用 Production Trace → Eval Dataset 反哺 hidden set  

---

## 8. 与本仓库的映射

| 组件 | 测评关注点 |
|------|------------|
| `travel-intake` | 是否 2～3 题、是否问人数、D=其他 |
| `gateway-chat-ui` | 问卷固定卡片、未提交前不跳过 |
| `lifecare__*` MCP | 工具存在性、轨迹顺序、耗时 |
| `workspace/SOUL.md` | A/B 阶段、禁未确认 4 人 |
| `MEMORY.md` | Pipeline eval 是否误用演示人设 |
| OpenClaw memory-core | Full pipeline retention |

---

## 9. 建议落地节奏（2 周）

| 周 | 动作 |
|----|------|
| W1 | 整理 50 条 Dev case（含你贴的「朋友未说人数」）；跑通 `eval_tool_trajectory` + 约束脚本 |
| W1 | 接 LangSmith/DeepEval 之一，只录 trace + tool 名 |
| W2 | 加 30 条 Hidden；做 20 条人评 rubric（完成度/合理性/可信度） |
| W2 | 写一页答辩：北极星 + Dev/Hidden 分数 + 1 个失败 case 归因（memory vs tool vs prompt） |

---

## 10. 一句话

你在做 有状态、有工具、有 OpenClaw 记忆的软件系统 QA；JSON 里的 `memory` 字段是 单元测试夹具，真正要测的是 记忆流水线 + 多轮槽位 + 工具轨迹 是否让行为真的变掉。




1. Agent 规则层（run_agent_eval.py · 19 条 cases.jsonl）
每条 case 在 expect 里写了才判；可能组合的 断言类型 如下：

指标 ID	含义
should_ask_intake_on_first_turn
首轮回复须含 A/B/C 选择题格式
should_ask_intake
最终回复须含选择题格式
forbidden_tools_before_intake
前几次工具调用不得出现 search/route
required_tools
必须调过列出的 MCP（如 weather、search_places）
required_tools_after_simulation
同上（命名表示答完题后应有，实现仍看全程工具列表）
must_not_contain_assistant
回复不得含某子串（如「4人」）
must_contain_assistant
回复须含某关键词
must_contain_assistant_after_followup
有模拟/追问时，最终回复须含某词
must_contain_categories_hint
方案须命中餐饮/博物馆等之一
max_first_token_ms
延迟上限（case 里基本未用）
missing_pred
未采集到该条 pred
汇总指标：passed / total、每条 pass（0/100 分）。

2. 采集统计 / 诊断（collect_openclaw_pred.py · case_scorecard.json）
不算 pass/fail（除非写入 expect），只记录：

字段	含义
latency_total_ms
该 case 多轮采集墙钟时间
first_turn_duration_ms / first_token_ms
来自 OpenClaw meta（常为 null）
turn_count / simulation_steps
对话轮次、模拟答题次数
tools_in_order
实际工具序列
failure_hints
启发式提示（如 no_mcp_tools_called）
3. Evaluator 汇总（run_evaluator.py）
在 Agent 规则之上多加：

指标	含义
rule_eval.passed/total
同上规则分
simulation_consistency
脚本答案 vs simulation_audit 是否一致
failure_diagnosis
失败项中文归因
overall_pass
规则全过 + 模拟一致
可选 deepeval
LLM judge 结果
4. 意图启发式（run_intent_eval.py · 4 条 intent_rules.jsonl）
不调模型，对 intent_heuristic.py 输出做字段相等判断：

字段	含义
scene
family / friends / ambiguous_family_or_friends 等
party_of_four
是否识别 4 人局
two_male_two_female_hint
2 男 2 女
child_age
孩子年龄
wife_low_oil_or_diet
老婆低油/减肥
likely_need_weather/search/route
是否倾向需要某类工具
5. MCP 工具层（run_mcp_benchmark.py · 37 条 scenarios.json）
不经 OpenClaw，直接调 lifecare 客户端：

指标	含义
min_pois / allow_zero_pois
POI 数量
each_poi_must_have_reputation
口碑/mock 字段完整
max_latency_ms
单次调用耗时上限
链路
weather、route_first_two_pois 等是否成功
6. 工具轨迹（eval_tool_trajectory.py · 5 条 gold_trajectories.jsonl）
指标	含义
required_recall
必需工具命中比例
required_hit / required_miss
命中/遗漏工具
forbidden_violations
是否调了禁止工具
order_ok
顺序是否正确（默认不启用）
mean_required_recall
全集平均
7. 可选 LLM Judge（run_deepeval_judge.py）
指标	含义
GEval ItineraryQuality
可执行性、约束满足、勿编造人数/排队（阈值 0.6）
需 ARK_API_KEY / OPENAI_API_KEY，默认不跑。

一键套件（run_eval_suite.py）会跑哪些
步骤	指标层
intent_eval
意图启发式 4 条
mcp_benchmark
MCP 37 条（可 --quick 3 条）
agent_eval + evaluator
Agent 19 条 + 模拟一致性
tool_trajectory
轨迹 5 条（目前 pred 多为样例）
intent_smoke
意图冒烟输出 JSON
和 AGENT_EVAL_PLAN.md 的差距
文档里还写了但 未单独成指标脚本 的包括：记忆 retrieval 断言、首 token SLA 门禁、规划绕路/总时长、同 seed 稳定性、Hidden 集等。

一句话：现在 有指标类型（上表），但 Agent 层不是「固定 rubric 自动套所有 case」，而是 每条 cases.jsonl 自己勾选 expect 里哪几条；用户话以外的 simulation 只服务自动多轮采集。若要改成「预先一套框架 + case 只有 user_text」，需要另做 rubric.json + scenario_type 映射（尚未实现）。