# 方案类长文输出 · 模型提示词清单

> 对照文档：[qwen方案类输出样例.md](./qwen方案类输出样例.md)（长沙亲子一日那篇）。  
> 下列是 **OpenClaw Agent 实际会读到的提示词来源**（线上 `https://121.41.81.58:8080/` 与 6.3 测评 **共用** `workspace/`，部署路径 `meituan-lifecare-agent/workspace/` → ECS `~/.openclaw/workspace/`）。

---

## 一、提示词是怎么进模型的

OpenClaw 赛题 Agent 启动时会按 `AGENTS.md` 指示加载工作区 Markdown；Skills 以独立 skill 文件注入（模型在相关场景下 `@` 或按 description 触发）。**没有**单独再写一条「请输出 3000 字方案」的系统 prompt——长文结构来自 **SOUL + local-itinerary-planner + 工具返回数据** 的组合。

| 层级 | 文件路径（仓库内） | 作用 |
|------|-------------------|------|
| 工作区引导 | `workspace/AGENTS.md` | 启动读 `SOUL.md`、`MEMORY.md`；指向 skills 与 SLA |
| **人设与总路由** | **`workspace/SOUL.md`** | 对话阶段、先问卷后方案、长文必须包含哪些块、工具习惯 |
| 模拟偏好 | `workspace/MEMORY.md` | 虚构用户偏好；**禁止**用来猜本轮人数/城市 |
| Skill · 补槽 | `workspace/skills/travel-intake/SKILL.md` | 2～3 道选择题、场景 A/B、槽位表 |
| **Skill · 出方案** | **`workspace/skills/local-itinerary-planner/SKILL.md`** | **7 段输出结构、工具链、POI 图链** |
| Skill · 口碑 | `workspace/skills/mock-user-prefs-reviews/SKILL.md` | 选点理由、reputation 字段用法 |
| Skill · 算路 | `workspace/skills/route-and-mobility/SKILL.md` | 相邻 POI 成对 `plan_route`、分钟/公里写进表 |
| 工具说明 | `workspace/TOOLS.md` | MCP 工具名与用途（辅助） |
| 网页专属注入 | `gateway-chat-ui/src/location.ts` | 首条用户消息后 **隐藏** 发 `[位置上下文]`（城市/区/坐标/场景 B 提示），**不是** SOUL 正文 |

**6.3 测评额外注入（网页没有）**：第一轮用户话前会拼 `[仿真环境-只读]`（虚构住址、订单摘要等），见 `测试/vitabench_eval/agent_bridge.py` 的 `format_environment_block`。样例里的 POI/天气仍来自真实 MCP。

---

## 二、样例长文每一块 · 对应哪条提示词

样例结构（见 `qwen方案类输出样例.md`）与提示词对照：

| 样例里看到的内容 | 主要来自 |
|------------------|----------|
| `# 🗺️ …方案` + **谁/哪/多久/主题** 总览 | `SOUL.md` §「完整方案长什么样」第 1 条；`local-itinerary-planner` §「输出结构」第 1 条 |
| `## 🌤️ 明日天气` + 表格 | `SOUL.md` §工具习惯「先 get_weather」；`local-itinerary-planner` §步骤 2 |
| `## 📍 动线总览` 文字链 + **Mermaid flowchart** | `SOUL.md` 第 5 条「Mermaid flowchart LR」；`local-itinerary-planner` 第 4 条 |
| `## 📋 行程速览表`（时段\|做什么\|交通\|备注） | `SOUL.md` 第 3 条；`local-itinerary-planner` 第 2 条 |
| `## 🕐 分时段展开` + 子标题 +  bullet | `SOUL.md` 第 4 条；`local-itinerary-planner` 第 3 条 |
| 段内 **`![](photo_urls…)`** 配图 | `SOUL.md`「图与链接」「配图位置」；`local-itinerary-planner` 第 7 条 |
| `[店名 →](amap_place_url)` 高德链接 | 同上；数据来自 `lifecare_search_places` 返回 |
| `## 💰 预算参考` 分项表 | `SOUL.md` 第 6 条；`local-itinerary-planner` 第 5 条 |
| `## 💡 Tips` 预约/带娃/备选 | `SOUL.md` 第 7 条；`local-itinerary-planner` 第 6 条 |
| 表内「打车约 X km / Y 分钟」 | `route-and-mobility` + `plan_route`；`local-itinerary-planner` §步骤 5 |
| 餐饮+文化/玩乐 **至少 3 锚点 + 正餐** | `local-itinerary-planner` §「交付与硬约束」半天/全天规模 |
| 语气「务实、友好、够长、够落地」 | `SOUL.md` 开篇人设一句 |
| 结尾追问「要不要调整午饭…」（样例有） | `SOUL.md` 大阶段一交付后仍可对话；**不是** STOP |

**样例之前通常还有一轮**：用户说意图 → Agent 出 **2～3 道选择题**（`travel-intake` + `SOUL.md` §A 槽位未齐）。样例截取的是 **槽位已齐、工具已跑完** 后的 B 阶段长文。

---

## 三、核心长文提示词原文（摘录）

### 1. SOUL.md · 人设 + 必须写长

```markdown
你是 美团本地生活场景下的出行规划管家，语气务实、友好；回答要写得够长、够落地，避免只丢两个店名就结束。
```

### 2. SOUL.md · 完整方案 7 块（与样例一一对应）

```markdown
1. 标题 + 一句话总览（谁、哪座城市、几天/半天、主题）。
2. 分区/动线概念（若适用：例如城东/城西、或「上午玩 / 中午吃 / 下午玩」）。
3. 行程速览表（Markdown 表格：`时段 | 做什么 | 交通方式 | 备注`）。
4. 分时段展开：每个点写清 停留约多久、为什么选它、口味/排队/预约提醒…
5. 路段级说明：关键段用 plan_route 的距离/分钟；可附 Mermaid flowchart LR 或 timeline。
6. 预算参考表（交通/门票/餐饮/其他分项 + 总计区间，声明为估算）。
7. Tips：预约、穿搭、带娃/老人、闭馆风险等。

图与链接：… amap_place_url … photo_urls … ![](url) … 禁止堆在文末。
```

### 3. SOUL.md · B 阶段（槽位齐才出样例这种长文）

```markdown
首字仍须快：先 一句「好的，正在并行查天气并检索地点…」
然后调用 lifecare__lifecare_get_weather，再 search_places / plan_route，
按 local-itinerary-planner 出 完整方案。
```

### 4. local-itinerary-planner/SKILL.md · 输出结构（Skill 侧硬性清单）

```markdown
## 输出结构（必须逐项出现）
1. 标题与总览句。
2. 行程速览：Markdown 表格（天数/时段 | 安排 | 交通）。
3. 分块详述：每段含 停留时长、选点理由、排队/预约/口味 提示。
4. 动线可视化：Mermaid flowchart/timeline 或 A→B + plan_route 分钟/公里。
5. 预算表：分项 + 总计区间（标注估算）。
6. Tips：预约、天气穿搭、闭馆、带娃等。
7. 图与链接：amap_place_url、photo_urls 嵌入对应段落。
```

### 5. local-itinerary-planner · 规模约束（防止只给两个店名）

```markdown
半天（约 4–6h）：至少 3 个可玩/可逛锚点 + 1 餐 … 禁止只输出 2 个店名结束。
全天：至少 4～6 个时段块（含午/晚餐 + 多个玩乐/文化）。
```

### 6. travel-intake（样例之前的问卷阶段，节选）

```markdown
仅 大阶段一 · 用户要完整行程且槽位未齐 时启用。
未完成本 skill 前 禁止 调用 search_places 与 plan_route。
第一条可见回复：复述场景 A/B + 2～3 个带编号选择题 + 「或直接回复：全部用默认」。
```

### 7. mock-user-prefs-reviews（选点理由、表格里「为什么选它」）

```markdown
规划前可读 mock/user_and_reviews.seed.json；
search_places 的 reputation 含高德 rating + mock 合成字段；
不得把 review_count_proxy 说成真实点评条数。
```

### 8. AGENTS.md · SLA（团队密度要求）

```markdown
槽位齐：完整方案 ≤ 3min，且须 长文 + 表格 + 预算 + Tips
（对齐 理想回答.md 密度，见 local-itinerary-planner）。
```

---

## 四、Skills 全列表（与样例关系）

| Skill | 是否直接决定样例长文形态 |
|-------|-------------------------|
| **local-itinerary-planner** | **是**（结构主清单） |
| **travel-intake** | 间接（先补槽，才有 B 阶段长文） |
| **mock-user-prefs-reviews** | 间接（选点与文案理由） |
| **route-and-mobility** | 间接（表内交通分钟/公里） |
| venue-queue-status | 可选（排队提示一句） |
| order-bundle-mock | 一般不出现（除非演示下单） |

---

## 五、网页 vs 测评 · 提示词差异（与样例相关部分）

| 项 | 网页 | 6.3 测评 batch |
|----|------|----------------|
| SOUL / skills | 相同 | 相同 |
| 位置/环境 | `[位置上下文]` 浏览器定位 | 首轮 `[仿真环境-只读]` 虚构住址/订单 |
| 用户话 | 真人输入 | 用户模拟 LLM（hidden instructions） |
| 结束 | 正常收尾，**禁止 STOP**（SOUL 已改） | 用户模拟器发 `###STOP###` |
| 模型 | Qwen3.6-Plus（网关） | 同左 |

---

## 六、文件路径速查（本地仓库）

```
meituan-lifecare-agent/workspace/
├── AGENTS.md
├── SOUL.md                    ← 人设 + 长文 7 块 + 阶段路由
├── MEMORY.md
├── skills/
│   ├── travel-intake/SKILL.md
│   ├── local-itinerary-planner/SKILL.md   ← 输出结构硬约束
│   ├── mock-user-prefs-reviews/SKILL.md
│   └── route-and-mobility/SKILL.md
└── mock/user_and_reviews.seed.json

gateway-chat-ui/src/location.ts   ← 网页 [位置上下文] 文案
测试/vitabench_eval/agent_bridge.py  ← 测评 [仿真环境] 文案（网页无）
```

如需看 **完整未摘录正文**，直接打开上表路径；SOUL 约 190 行，local-itinerary-planner 约 54 行，travel-intake 约 158 行。
