# MCP 场景评测（本机跑，不经过 OpenClaw）

用于在 同一台机器 上复现「工具层是否满足赛题脚本里的硬条件」，避免在 OpenClaw 里手工多轮对话压测。

## 0. 一句话分清两件事（不讲「故事体量」）

| 像什么 | 是什么 | 文件大概长啥样 |
|--------|--------|----------------|
| 教模型做题的习题册 | 微调 / SFT：要标准答案（该调哪些工具、输出啥计划） | 多条「对话 + 标准答案」→ 常为 JSONL |
| 体检表 | 测 Agent 工具是否正常：给输入，看高德/天气返回对不对 | 一条条「城市 + 关键词 + 期望」→ 本目录 `scenarios.json` |

两套可以 题目类似（都在说「杭州亲子博物馆」），但 用途不同：习题册用来训练；体检表用来自动验收。所以：划分思路可以一样（train/val/test），文件不是同一种。

## 1. 固定 Python 打分 vs「训练小模型」

- 规则 / 启发式 / 确定性 mock（你们现在的 `reputation` 等）：全是 固定代码 + 配置，不需要训练。
- 只有当你希望从日志里 学出 非线性权重（例如 XGBoost/LightGBM 重排）时，才需要 Train/Val 带标签数据；那是另一条路线，与「黑客松先把链路跑通」无必然关系。

## 2. 「微调大模型」的数据 vs本目录「场景评测」

| 用途 | 内容 | 是否对应之前说的 Train/Val/Test 划分 |
|------|------|----------------------------------------|
| SFT / 教模型写计划、调工具 | 多轮对话 + gold 工具序列或结构化计划（可选 DPO 对） | 是，可沿用「200～2000 / 人标 Val / 冻结 Test」那条建议，但 文件格式是训练 JSONL，不是本目录的 `scenarios.json`。 |
| 评测 Agent（OpenClaw + MCP） | 用户自然语言 + 是否带 `【历史偏好】` + 城市 + 对工具返回的断言 | 本目录 `scenarios.json` + `run_mcp_benchmark.py`：只验证 MCP 与数据字段，不验证大模型遣词造句（那部分仍需小样本人评或接 OpenClaw 轨迹日志）。 |

结论：微调数据集 ≠ `scenarios.json`；`scenarios.json` 是 集成/回归测试，可与 OpenClaw 演示脚本 对照同一组城市与关键词。

## 3. 本机怎么跑

在项目根目录（本仓库）执行：

```powershell
cd "D:\projects\meituan hackathon\meituan-lifecare-agent"
# 使用上级或本目录 .env 中的 AMAP_KEY（与 MCP 一致）
python benchmark/run_mcp_benchmark.py
```

可选：

```powershell
python benchmark/run_mcp_benchmark.py --scenarios benchmark/scenarios.json --out benchmark/results
python benchmark/run_mcp_benchmark.py --only hz_museum,sh_coffee
```

全量 37 条里，约前 12 条含「天气 + 两段驾车路径」（最慢）；其余多为 仅 POI 搜索（扩城市覆盖、单条更快）。外网+高德正常时，全量跑完可能 数分钟～十几分钟，日常请用 `--only` 跑子集。

退出码：任一场景失败则为 `1`，便于 CI。

## 4. 放进 OpenClaw 怎么「复刻」

OpenClaw 侧 不会自动执行 本脚本；推荐做法：

1. 把 `benchmark/scenarios.json` 复制到团队仓库，作为 演示用例清单（评委可对照 `id` 提问）。
2. 答辩材料里贴 `benchmark/results` 里最近一次生成的 `report_*.json`（本机跑完后提交或打印摘要）。
3. Agent 的 `lifecare_search_places` 参数与脚本一致：`extensions=all`、`attach_mock_reputation=true`（默认）。

若你希望 完全同一组关键词，在 OpenClaw 里让用户说与 `scenarios.json` 中 `user_prompt_hint` 一致的句子即可。可选字段 `suggested_user_id` 与 `workspace/mock/user_and_reviews.seed.json` 里的 `user_id` 对齐，便于演示「带历史偏好人设」；跑分脚本不读取该字段。

## 5. 大模型「意图 + 选工具」我能自动测到什么程度？

| 脚本 | 测什么 | 要不要 OpenClaw / Key |
|------|--------|-------------------------|
| `run_mcp_benchmark.py` | 高德/天气/MCP 返回与 `reputation` 字段 | 要 AMAP_KEY，不要 OpenClaw |
| `run_intent_smoke.py` | 规则基线意图（见 `intent_heuristic.py`），输出写到 `benchmark/results/intent_smoke_latest.json` | 都不要 |
工具轨迹：由 `run_agent_eval.py` 的 rubric 对照 pred 里的 `tools_in_order` 判断，无需单独 gold 文件。

## 6. 意图关键词当前怎么分（规则版）

实现见 `benchmark/intent_heuristic.py`（与模型无关）：

- 家庭：`老婆孩子`、`孩子`、`带娃`、`亲子`…  
- 朋友：`朋友`、`聚会`、`4个人`、`2男2女`…  
- 赛题首句里同时出现 `老婆孩子/朋友`：标成 `ambiguous_family_or_friends` → 设计上应走 `travel-intake` 二选一，而不是硬猜。  
- 补充句「孩子5岁，老婆减肥」→ `scene=family`，`child_age=5`，`wife_low_oil_or_diet=true`。  
- 补充句「4人 2男2女」→ `scene=friends`，`party_of_four=true`。

大模型上线后：可把 模型输出的槽位 与上述规则做 一致性抽检（不要求完全一致，只抓明显矛盾）。

## 7. 不用 OpenClaw 的「本地小 Agent」

赛题 交作品 若要求必须基于 OpenClaw，答辩/交付仍要跑 OpenClaw。  
开发自测可用 `scripts/run_local_agent.py`：与 MCP 同一套 Python 实现，可选 不调大模型（--dry） 或 OpenAI 兼容 API + 工具循环，不必起 OpenClaw 网关。

```powershell
python scripts/run_local_agent.py --dry -m "下午在杭州带娃逛博物馆" -o benchmark/results/local_agent_dry.json
# LLM 模式需 LLM_API_KEY，可选 LLM_BASE_URL、LLM_MODEL
python scripts/run_local_agent.py -m "帮我安排杭州半日亲子" -o benchmark/results/local_agent_llm.json
```

OpenClaw 额外提供：飞书/微信等 渠道、Skill 注入与快照、会话与策略配置；本脚本只覆盖 「模型 + 三五个工具」 的最小闭环，不能在赛题层面完全替代 OpenClaw。

## 8. 固定 Rubric（不需每条 case 打标）

- `benchmark/rubric.json`：全站评分表（intake、禁预设人数、工具框架等）；`desc` 给人看，判分由 `rubric_engine.py` 代码执行。
- `benchmark/rubric_context.py`：从用户 `user_text`（及多轮 user_messages） 自动推断适用规则（如是否槽位不齐、是否查天气、是否该走完整 天气→搜点→路线）。
- `eval_cases/dev/cases.json`：每项 `user_text` + `user_facts`（写全槽位）；采集默认 `reply_mode: choices`——根据 Agent 实际出的题 自动选 A/B/C/D，详见 `eval_cases/dev/README.md`。

```powershell
python benchmark/run_agent_eval.py --pred benchmark/results/agent_pred_live.jsonl
```

报告里每条含 `context`（自动推断）、`rules_applied`、`tools_vs_framework`、`dimension_scores` + `total_score`（0-100，对齐赛题六维）。

采集模拟用户（`cases.json`）：

- `reply_mode: choices`（默认）：读 `user_facts`，匹配助手 intake 各题选项 → 发送 `选择题答案：第1题选B…`（与 Web 按钮一致）。
- `reply_mode: llm`：口语（仅特殊需要时）。
- `collect_openclaw_pred.py --sim-mode choices` 为默认。

```powershell
python benchmark/collect_openclaw_pred.py --sim-mode auto
python benchmark/run_agent_eval.py --pred benchmark/results/agent_pred_live.jsonl
python benchmark/build_case_scorecard.py --eval benchmark/results/agent_eval_latest.json
```

## 9. 一键 Agent 测评套件（无需注册 SaaS）

```powershell
python benchmark/run_eval_suite.py --skip-mcp          # 无高德 Key 时
python benchmark/run_eval_suite.py --quick             # MCP 子集 3 条
python benchmark/run_eval_suite.py --with-openclaw     # 采集 + 多轮模拟答题 + evaluator

# 仅采集（ECS/本机 openclaw + 网关）
python benchmark/collect_openclaw_pred.py              # 19 条 dev，写 pred + simulation_audit
python benchmark/run_evaluator.py --pred benchmark/results/agent_pred_live.jsonl
```

- 规模（当前）：Agent 19 条（`cases.json`）、MCP 37 条（`scenarios.json`）。  
- 模拟用户：采集后对照 `simulation_audit.jsonl`（含助手题目摘录 + 发送的答案）。  
- Evaluator：`run_evaluator.py` = 规则分 + 模拟一致性 + 失败归因（可选 `--with-deepeval`）。  
- 汇总：`evaluator_report.json` / `eval_suite_latest.json`。详见 `docs/EVAL_YOU_NEED.md`。
