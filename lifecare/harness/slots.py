from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


INTAKE_SUBMISSION_RE = re.compile(r"^选择题答案：", re.M)
PARTY_PATTERNS = [
    re.compile(r"两大一小"),
    re.compile(r"两大两小"),
    re.compile(r"(\d+)\s*大\s*(\d+)\s*小"),
    re.compile(r"我们\s*(\d+)\s*个"),
    re.compile(r"(\d+)\s*人"),
    re.compile(r"(\d+)\s*个朋友"),
    re.compile(r"带娃|亲子|孩子\s*\d+\s*岁"),
]
CITY_PATTERN = re.compile(
    r"(北京|上海|广州|深圳|杭州|南京|成都|重庆|武汉|西安|苏州|天津|青岛|大连|厦门|长沙|郑州|合肥|福州|昆明|贵阳|海口|三亚|宁波|无锡|常州|扬州|绍兴|嘉兴|湖州|金华|台州|温州|佛山|东莞|珠海|中山|惠州|济南|石家庄|哈尔滨|长春|沈阳|南昌|南宁|兰州|银川|乌鲁木齐|拉萨|呼和浩特)"
)
REPLAN_HINTS = re.compile(r"改午饭|改方案|重新规划|换一天|改成|改为|压缩|换室内|换景点|改人数|改室内|下雨了")
QA_HINTS = re.compile(r"^(为什么|怎么|多久|几点|在哪|是否|能不能|可以|预约|停车|地铁|步行)", re.M)
PLAN_MARKERS = re.compile(r"行程速览|##\s*📋|时段\s*\|\s*做什么|<!--\s*plan_complete\s*-->")
PLANNING_INTENT_RE = re.compile(
    r"安排|规划|行程|去哪玩|半日|一日|逛逛|出游|带娃出门|聚会怎么玩|帮我.plan|玩什么|附近玩|怎么玩|在.{0,8}玩|出门玩"
)
WEATHER_ONLY_RE = re.compile(r"天气|气温|下雨|降温|穿衣|冷吗|热吗|预报|降雨|风力")
CHITCHAT_RE = re.compile(
    r"^(你好|谢谢|您好|在吗|哈喽|hi|hello|好的|嗯|收到|再见|拜拜)[!！?？。.\s]*$",
    re.I,
)
CITY_CHANGE_RE = re.compile(
    r"不去.{0,6}了|改去|换成|换到|改.{0,4}(玩|去)|从.{0,6}改"
)


@dataclass
class Slots:
    ready: bool = False
    party_size: bool = False
    city: str | None = None
    trip_days: int = 1
    half_day: bool = False
    anchors_per_day: int = 4
    intake_submitted: bool = False
    user_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "party_size": self.party_size,
            "city": self.city,
            "trip_days": self.trip_days,
            "half_day": self.half_day,
            "anchors_per_day": self.anchors_per_day,
            "intake_submitted": self.intake_submitted,
        }


def _detect_party_size(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    for pat in PARTY_PATTERNS:
        if pat.search(t):
            return True
    if re.search(r"第\d+题选[A-F]", t) and re.search(r"人数|同行|几位", t):
        return True
    return False


def _detect_half_day(text: str) -> bool:
    return bool(re.search(r"半\s*天|3\s*小时|几小时|今晚|下午|上午", text))


def _detect_trip_days(texts: list[str]) -> int:
    blob = " ".join(texts)
    m = re.search(r"(\d+)\s*日", blob)
    if m:
        return max(1, min(7, int(m.group(1))))
    if re.search(r"两日|两天|2\s*天", blob):
        return 2
    if re.search(r"三日|三天|3\s*天", blob):
        return 3
    if _detect_half_day(blob):
        return 1
    return 1


def parse_slots_from_messages(messages: list[str]) -> Slots:
    slots = Slots(user_messages=list(messages))
    blob = "\n".join(messages)

    if INTAKE_SUBMISSION_RE.search(blob):
        slots.intake_submitted = True
        slots.ready = True

    for msg in messages:
        if _detect_party_size(msg):
            slots.party_size = True
        cm = CITY_PATTERN.search(msg)
        if cm and not slots.city:
            slots.city = cm.group(1)

    slots.half_day = _detect_half_day(blob)
    slots.trip_days = _detect_trip_days(messages)
    slots.anchors_per_day = 3 if slots.half_day else 4

    if not slots.ready:
        planning_intent = re.search(
            r"安排|规划|行程|去哪玩|半日|一日|逛逛|出游|带娃出门|聚会怎么玩",
            blob,
        )
        if planning_intent and slots.party_size and slots.city:
            slots.ready = True
        if planning_intent and INTAKE_SUBMISSION_RE.search(blob):
            slots.ready = True
        if re.search(r"全部用默认|直接回复.*默认", blob):
            slots.ready = True

    return slots


def detect_replan_intent(last_user: str) -> bool:
    return bool(REPLAN_HINTS.search(last_user or ""))


def detect_qa_intent(last_user: str, has_plan: bool) -> bool:
    if not has_plan:
        return False
    t = (last_user or "").strip()
    if not t or detect_replan_intent(t):
        return False
    if len(t) < 80 and QA_HINTS.search(t):
        return True
    if has_plan and len(t) < 40 and "?" in t or "？" in t:
        return True
    return False


def detect_full_plan(assistant_text: str) -> bool:
    return bool(PLAN_MARKERS.search(assistant_text or ""))


def detect_planning_intent(blob: str) -> bool:
    return bool(PLANNING_INTENT_RE.search(blob or ""))


def detect_light_weather(last_user: str, blob: str = "") -> bool:
    t = (last_user or "").strip()
    if not t or not WEATHER_ONLY_RE.search(t):
        return False
    if detect_planning_intent(t):
        return False
    if detect_planning_intent(blob) and not WEATHER_ONLY_RE.search(blob.replace(t, "")):
        return False
    return True


def detect_chitchat(last_user: str) -> bool:
    t = (last_user or "").strip()
    if not t:
        return False
    if detect_planning_intent(t) or WEATHER_ONLY_RE.search(t):
        return False
    return bool(CHITCHAT_RE.match(t)) or len(t) <= 6


def detect_city_change(last_user: str, current_city: str | None) -> bool:
    t = last_user or ""
    if not CITY_CHANGE_RE.search(t):
        return False
    for cm in CITY_PATTERN.finditer(t):
        city = cm.group(1)
        if current_city and city != current_city:
            return True
    if re.search(r"换城市|整趟|换纲|改去别的", t):
        return True
    return False
