"""
意图 / 槽位 · 纯规则基线（不调用大模型）。

用途：
1) 黑客松答辩时说明「当前关键词怎么分」——这是启发式，最终应以大模型+Skill为准；
2) 给自动评测脚本做弱标签，对比「模型输出槽位」与规则是否严重冲突。

赛题原文（命题六）典型句见 benchmark/README.md 引用。
"""
from __future__ import annotations

import re
from typing import Any


def classify_intent_heuristic(user_text: str) -> dict[str, Any]:
    t = (user_text or "").strip()
    low = t.lower()

    # --- 人群场景（家庭 / 朋友 / 需澄清）---
    family_hit = bool(
        re.search(
            r"老婆\s*孩子|老婆孩子|孩子|带娃|亲子|小孩|宝宝|儿\s*子|女\s*儿|儿童|幼儿园|小学",
            t,
        )
    )
    friend_hit = bool(
        re.search(
            r"朋友|闺蜜|兄弟|聚会|同学|室友|[二三四五六七八两]\s*个\s*人|"
            r"[24四]\s*个\s*人|[男女]\s*生|[男女]\s*士",
            t,
        )
    )
    # 赛题里「老婆孩子/朋友」同句出现：视为「二选一未选定」→ 需要反问
    slash_or = bool(re.search(r"老婆孩子\s*/\s*朋友|朋友\s*/\s*老婆孩子", t))
    if slash_or and family_hit and friend_hit:
        scene = "ambiguous_family_or_friends"
    elif family_hit and not friend_hit:
        scene = "family"
    elif friend_hit and not family_hit:
        scene = "friends"
    elif family_hit and friend_hit:
        scene = "mixed_crowd"
    else:
        scene = "unknown"

    # --- 时间范围 ---
    half_day = bool(
        re.search(r"几\s*个\s*小\s*时|半\s*天|半\s*日|4[-~至到]\s*6|四\s*到\s*六|下午|晚上|周末|空\s*的", t)
    )
    time_scope = "half_day_or_few_hours" if half_day else "unknown"

    # --- 家庭补充条件（赛题 bullet）---
    child_age = None
    m = re.search(r"孩子\s*(\d{1,2})\s*岁", t)
    if m:
        child_age = int(m.group(1))
    wife_diet = bool(re.search(r"老婆.*减肥|减肥|低油|低糖|清淡", t))

    # --- 朋友补充（4 人 2 男 2 女）---
    party_four = bool(re.search(r"4\s*个\s*人|四个\s*人|总共\s*4", t))
    gender_balance = bool(re.search(r"2\s*个\s*男|两\s*个\s*男", t)) and bool(
        re.search(r"2\s*个\s*女|两\s*个\s*女", t)
    )

    # --- 地理 / 出行 ---
    stay_near_home = bool(re.search(r"别离家太远|离家近|附近|别太远|不要太远", t))

    # --- 与工具相关的「意图标签」（仍由 Agent 决定是否真调工具）---
    likely_need_weather = bool(re.search(r"下午|户外|公园|江滩|海边|散步|玩", t))
    likely_need_search = True  # 规划类默认需要 POI
    likely_need_route = bool(re.search(r"路线|先后|顺序|怎么去|动线|安排", t))

    return {
        "scene": scene,
        "time_scope": time_scope,
        "constraints": {
            "child_age": child_age,
            "wife_low_oil_or_diet": wife_diet,
            "party_of_four": party_four,
            "two_male_two_female_hint": gender_balance,
            "stay_near_home": stay_near_home,
        },
        "tool_intent_hints": {
            "likely_need_weather": likely_need_weather,
            "likely_need_search": likely_need_search,
            "likely_need_route": likely_need_route,
        },
        "_note": "规则基线，非大模型输出；ambiguous 时应走 travel-intake 反问。",
    }
