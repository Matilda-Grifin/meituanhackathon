---
name: mock-user-prefs-reviews
description: 用户历史偏好与评价语料均为 mock；可读 workspace/mock 种子 JSON；可离线接入开源中文点评语料，不得冒充线上真实库。
---

# Mock 用户偏好与评价语料

## 何时使用

任何涉及「用户历史偏好」「评价摘录」「口碑总结」的环节：规划、打分说明、POI 对比时启用。

## 数据来源（mock）

- 本仓库种子数据：`workspace/mock/user_and_reviews.seed.json`（虚构用户画像 + 虚构短评），字段定义见同目录 `user_profile.schema.json`、`mock_review.schema.json`。演示时可按 `user_id` 选用，或对种子列表 随机抽一用户 注入上下文。
- 偏好与人设兜底：以 `MEMORY.md`、`SOUL.md` 及用户当轮口述为准；与种子文件冲突时 以用户当轮为准。
- POI 侧口碑（检索工具内）：`lifecare__lifecare_search_places` 默认返回 `reputation`：含高德 `biz_ext.rating`（仅部分类目） 与 确定性 mock 合成的 `for_weights`。排序时用它，但 不得 将 `review_count_proxy` 等说成美团/点评真实评论量。
- 可复用的外部语料（须自行下载、遵守许可、建议仅离线使用）：
  - [Meituan-Dianping/asap](https://github.com/Meituan-Dianping/asap)：方面级情感标注语料（Apache-2.0），适合练 摘要/情感词表，勿整表塞进单次 Prompt。
  - ChineseNlpCorpus · yf_dianping（SophonPlus）：研究用大众点评风格数据，数据在网盘不在 Git，说明见 [intro.ipynb](https://github.com/SophonPlus/ChineseNlpCorpus/blob/master/datasets/yf_dianping/intro.ipynb)；体积大，适合做 离线 统计或风格对齐后再生成短句。
  - 高校/数据平台开放集（如北大开放数据等）：常为地域或品类子集，适合做 分布校准，仍不建议当「线上实时评价」使用。

## 步骤

1. 规划前：若有演示 `user_id`，读种子 JSON 中 `taste_tags`、`travel_style`、`history_summary` 及该用户的 `reviews`。
2. 在输出里区分三档：用户当轮明确说的 | 种子文件中的 mock | 模型推断（须标注）。
3. 若需「评价」支撑选点理由，用 1–2 句短评 + 星级/方面标签；合成内容须口头等价声明「演示生成」。

## 边界

- 不把 mock 偏好写入工具参数冒充第三方用户画像 API（直至后端提供真实接口）。
- 与真实高德 POI 混用时，明确：POI 与坐标来自高德；画像与评论为演示种子或离线研究语料加工结果。
