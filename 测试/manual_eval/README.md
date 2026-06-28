# 人工评测 10 Tasks · 日志与自动打分

前端 Web 测完一条 Task 后，日志写入 ECS：

```
/root/meituan-lifecare-agent/测试/eval_logs/eval_manual_YYYY-MM-DD.jsonl
```

## 测之前

1. **Ctrl+F5** 硬刷新页面（当前线上包须含 `index-D41G2oM3.js` 或更新；旧包会漏记 `turn_complete` / `intake ttftMs`）。
2. **每个 Task 新建会话**；首条消息任选一种打标方式：
   - 消息开头写 `[T063_002]`，例如：`[T063_002] 带娃在家附近玩半天，别太折腾`
   - 或 URL 加参数：`?eval_task=T063_002`
3. **多人并行测时**无需手动设测试者名；每条 eval 事件自动带 `deviceId`（本浏览器固定 ID），日志可按 device 区分。
4. **定位在杭州等地时**，请用 [`docs/6.3测评/人工评测_10任务集_浏览器定位版.md`](../docs/6.3测评/人工评测_10任务集_浏览器定位版.md) 的话术，不要用原考卷里的「去北京/春熙路/虹桥」首句。
5. 按 [`docs/6.3测评/人工评测_10任务集.md`](../docs/6.3测评/人工评测_10任务集.md) 或浏览器定位版多轮话术测完该 Task。

## 日志事件类型

| event | 含义 |
|-------|------|
| `session_start` | 新建会话 / 首条 user 发送（含 `modelId`） |
| `model_switch` | 顶部切换全局模型 |
| `intake_shown` | A 阶段 IntakeCard 出现 + ttftMs |
| `intake_submitted` | 提交选择题 |
| `tool_progress` | B 阶段任务进展区出现工具行 |
| `turn_complete` | 每轮 WS final（含 ttft/duration/toolCalls/totalTokens）；**每轮仅 1 条**（去重） |
| `image_gen_start` / `image_gen_complete` | 生图端到端 |

同时合并 **OpenClaw session jsonl**（工具名、token、完整方案正文）做 rubric 规则打分。

每条 eval 事件还可带顶层字段 **`modelId`**、**`deviceId`**（本浏览器 UUID）、**`testerLabel`**（URL `?tester=`），打分报告 `report_*.json` 的 sessions 数组会输出这三项。

## 测完之后：自动出分

**ECS 上：**

```bash
cd /root/meituan-lifecare-agent
python3 测试/manual_eval/score_from_logs.py --date 2026-06-23 \
  --write-md 测试/eval_logs/report_2026-06-23.md \
  --json-out 测试/eval_logs/report_2026-06-23.json
```

**或 HTTP：**

```bash
curl -sk -X POST 'https://121.41.81.58:8080/api/eval/score' \
  -H 'Content-Type: application/json' -d '{"date":"2026-06-23"}'
```

报告含：

- **Mean Reward** / **Full Success Rate**（reward=1.0）
- 每条 rubric 自动判定（✅/❌ + 依据）
- A 阶段 intake ≤10s、B 工具进展可见、生图 ms、Token、tools/turn

> 自动 rubric 为**规则启发式**，Hard 任务（高铁/无障碍）建议人工抽检 justification；脚本输出可直接填入评分表。  
> **浏览器定位实测**请用 [`docs/6.3测评/人工评测_10任务集_浏览器定位版.md`](../docs/6.3测评/人工评测_10任务集_浏览器定位版.md)（话术与 rubric 以页顶定位为准，不要求北京/上海等地名）。

## 本地

```powershell
cd "D:\projects\meituan hackathon\meituan-lifecare-agent"
python 测试/manual_eval/score_from_logs.py --date 2026-06-23
```

（需本机有相同路径的 `eval_logs` 与 `~/.openclaw/.../sessions`，或从 ECS scp 下来。）
