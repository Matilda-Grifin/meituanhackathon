# 测评：你要准备什么（务实版）

## 结论：会不会更好？

| 工具 | 建议 | 原因 |
|------|------|------|
| 本仓库 benchmark 脚本 | ✅ 必用 | 已覆盖 MCP、工具轨迹、意图规则；零注册 |
| DeepEval | ⚡ 可选 | 只在你想自动评「回答写得好不好」时；`pip` + API Key 即可，不必注册 Confident AI |
| Promptfoo | ⚡ 可选 | 改 SOUL 时做 A/B；`npm i -g promptfoo`，不必账号（用 OpenAI/兼容 API 当裁判时要有 Key） |
| LangSmith / Braintrust | ❌ 黑客松跳过 | 要账号、接链路成本高，答辩 ROI 低 |

已在仓库落地：`benchmark/eval_cases/dev/cases.json` + `run_agent_eval.py`（规则断言，无第三方账号）。

---

## 你必须准备的（三层）

### 1. 环境 Key（已有则跳过）

| 变量 | 用途 |
|------|------|
| `AMAP_KEY` | `run_mcp_benchmark.py` 测高德 |
| `ARK_API_KEY` 或豆包 | OpenClaw 跑 Agent |
| （可选）`OPENAI_API_KEY` | DeepEval / Promptfoo 当裁判 |

### 2. 考卷数据（约 1～2 小时整理）

- MCP 层：继续用 `benchmark/scenarios.json`（37 条已有）
- Agent 层：编辑 `benchmark/eval_cases/dev/cases.json`，按你们赛题加 case
- 工具是否达标：看 `run_agent_eval` 报告里的 `tools_vs_framework`（pred 里已有 `tools_in_order`）

### 3. 每次发版跑一次的「pred」导出（半自动）

对每条 `case_id` 在 http://121.41.81.58:8080/ 或 `openclaw agent` 跑一遍，记下：

- `assistant_text`（最终助手正文）
- `tools_in_order`（调了哪些 lifecare 工具）
- `user_messages`（用户说了啥）
- （可选）`latency_first_token_ms`

写成 JSONL：`benchmark/results/agent_pred_live.jsonl`（由 `collect_openclaw_pred.py` 生成）。

---

## 推荐命令（零注册）

```powershell
cd "D:\projects\meituan hackathon\meituan-lifecare-agent"

# ① 工具/MCP 体检（要快可先 --only hz_museum）
python benchmark/run_mcp_benchmark.py

# ② 意图规则冒烟
python benchmark/run_intent_smoke.py

# ③ Agent 规则评测（需先采集 pred）
python benchmark/collect_openclaw_pred.py
python benchmark/run_agent_eval.py --pred benchmark/results/agent_pred_live.jsonl
```

---

## 可选：DeepEval（不注册 Confident AI）

```powershell
pip install -r benchmark/requirements-eval-optional.txt
# 准备 judge 输入 JSONL：case_id, user_text, assistant_text
python benchmark/run_deepeval_judge.py --input benchmark/sample_judge_input.jsonl
```

需要：能调通的裁判 API（`ARK_API_KEY` 或 `OPENAI_API_KEY`）。  
评的是「文案质量」，不替你做工具轨迹检查。

---

## 可选：Promptfoo

```powershell
npm install -g promptfoo
$env:OPENAI_API_KEY="sk-..."
cd meituan-lifecare-agent
promptfoo eval -c benchmark/promptfooconfig.yaml
```

适合：改 `SOUL.md` 后快速看「是否还会擅自写 4 人」。  
不会自动连 OpenClaw；`actual` 要你自己贴或以后接 CLI。

---

## 不需要准备的

- LangSmith / Braintrust 账号  
- Confident AI 云账号（除非你要在线看板）  
- 几百个「真实客户」记忆库——用 case + session / MEMORY 快照 即可  

---

## 答辩最小集（建议）

1. `run_mcp_benchmark.py` 最近一次 `report_*.json` 摘要  
2. `run_agent_eval.py` 通过率 + 1 条失败 case 截图（如「朋友未说人数却出现 4 人」）  
3. `run_agent_eval` 的 `tools_vs_framework` / 总分  
4. 一页表：Dev 用例覆盖 §4 哪几类（槽位/记忆/工具/首 token）
