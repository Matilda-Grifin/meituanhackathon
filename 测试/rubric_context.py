#!/usr/bin/env python3
"""从用户原话（可多条）推断适用哪条 rubric，无需每条 case 打标。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_CITIES = r"北京|上海|广州|深圳|杭州|成都|重庆|南京|武汉|西安|苏州|厦门|三亚|哈尔滨|乌鲁木齐|拉萨|合肥|郑州|昆明|兰州|太原|济南|福州|南宁|桂林|长春|贵阳|呼和浩特|青岛|大连|宁波|无锡|东莞|佛山|香港|澳门|台北"
_LOCATION_HINT = r"夫子庙|春熙路|外滩|西湖|天河区|静安|朝阳|美术馆|博物馆|商场|公园|火锅|咖啡|小吃|商业街|步行街"
_PARTY_IN_USER = re.compile(
    r"(\d+)\s*人|一共\s*(\d+)|总共\s*(\d+)|[两二三四五六七八]\s*大\s*[一二三四五六七八]?\s*小|"
    r"2\s*成\s*人|\d+\s*成\s*人|3-4\s*人|4\s*个\s*人|2\s*男\s*2\s*女|"
    r"选\s*[A-D].*?(\d+)\s*人",
    re.I,
)
_PARTY_IN_REPLY = re.compile(
    r"(?:共|一共|总共|约|有)\s*(\d+)\s*[人位]|(\d+)\s*人(?:同行|小聚|一起|聚餐|游玩)|"
    r"适合\s*(\d+)\s*人|(\d+)\s*人(?:的|小)?(?:团体|群体|局)",
    re.I,
)
_VAGUE = re.compile(r"帮我安排|安排一下行程|想出去玩|还没想好|不知道去哪|有空", re.I)
_WEATHER = re.compile(r"天气|气温|预报|下雨|降水|几度|forecast", re.I)
_PLAN = re.compile(
    r"玩|行程|安排|规划|逛|吃|博物馆|咖啡|火锅|公园|美术馆|小吃|带娃|亲子|"
    r"散步|展览|商场|聚一下|出游|半\s*天|一\s*天|今晚|下午",
    re.I,
)
_ABUSE = re.compile(
    r"黑进|黑客|入侵|盗取|钓鱼网站|窃取银行卡|诈骗网站|木马|病毒程序",
    re.I,
)
_AMBIG = re.compile(r"老婆孩子\s*/\s*朋友|朋友\s*/\s*老婆孩子", re.I)
_FRIEND = re.compile(r"朋友|闺蜜|同学|聚会", re.I)
_DEFAULTS = re.compile(r"全部用默认", re.I)


@dataclass
class RubricContext:
    flags: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def get(self, key: str) -> bool:
        return bool(self.flags.get(key))


def infer_context(user_messages: list[str]) -> RubricContext:
    text = " ".join(m.strip() for m in user_messages if m.strip())
    ctx = RubricContext()

    if _ABUSE.search(text):
        ctx.flags["abuse"] = True
        ctx.notes.append("abuse_detected")
        return ctx

    weather_primary = bool(_WEATHER.search(text)) and not (
        _PLAN.search(text) and not re.match(r"^查.+天气", text.strip())
    )
    planning = bool(_PLAN.search(text)) and not weather_primary
    has_location = bool(re.search(_CITIES, text)) or bool(re.search(_LOCATION_HINT, text))
    has_time = bool(re.search(r"半\s*天|一\s*天|今晚|下午|上午|几\s*个\s*小\s*时|1\s*人", text))
    party_given = bool(_PARTY_IN_USER.search(text)) or bool(_DEFAULTS.search(text))
    vague = bool(_VAGUE.search(text))
    ambiguous = bool(_AMBIG.search(text))
    friend_no_count = bool(_FRIEND.search(text)) and not party_given

    slots_incomplete = vague or ambiguous or (friend_no_count and planning) or (
        planning and not has_location and not _DEFAULTS.search(text)
    )
    if weather_primary and not planning:
        slots_incomplete = False

    planning_ready = planning and not slots_incomplete and not weather_primary
    planning_full_chain = planning_ready and (has_location or has_time) and not re.search(
        r"只查|仅查|只要.*天气", text
    )

    ctx.flags = {
        "weather_primary": weather_primary,
        "planning_intent": planning,
        "slots_incomplete": slots_incomplete,
        "party_size_not_given": not party_given,
        "planning_ready": planning_ready,
        "planning_full_chain": planning_full_chain,
    }
    if party_given:
        ctx.notes.append("party_size_in_user_text")
    if slots_incomplete:
        ctx.notes.append("slots_incomplete")
    return ctx


def find_unconfirmed_party_in_reply(assistant_text: str) -> list[str]:
    """回复里像「既定人数」的片段（用于失败说明）。"""
    hits: list[str] = []
    for m in _PARTY_IN_REPLY.finditer(assistant_text or ""):
        g = next((x for x in m.groups() if x), None)
        if g:
            hits.append(f"{g}人")
    return hits
