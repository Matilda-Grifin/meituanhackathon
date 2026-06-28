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
# 规划上下文词：出现即说明在安排出行（即便没命中 PLANNING_INTENT_RE）。
# light_weather 据此改为 fail-open：只有「明确纯查天气」才降级，拿不准一律放行规划。
PLANNING_CONTEXT_RE = re.compile(
    r"看展|展览|博物馆|美术馆|画展|公园|湖边|景点|景区|古镇|寺庙|乐园|游乐|"
    r"吃|餐|饭|菜|午餐|晚餐|早餐|咖啡|奶茶|探店|美食|"
    r"行程|路线|动线|安排|玩|逛|散步|走走|遛|出游|一日|半日|半天|"
    r"带娃|亲子|孩子|老人|朋友|约会|情侣|闺蜜|"
    r"门票|预约|停车|地铁|打车|步行|怎么去"
)
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
    intake_consumed: bool = False
    intake_mode: str | None = None  # formal | defaults | skipped_freetext
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
            "intake_consumed": self.intake_consumed,
            "intake_mode": self.intake_mode,
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


FREETEXT_INTAKE_HINTS = re.compile(
    r"地铁|自驾|打车|公交|步行|半天|一天|几小时|不忌口|口味|忌口|"
    r"老人|孩子|带娃|朋友|情侣|家庭|创意菜|清淡|辣|不辣|"
    r"第\d+题选[A-F]|选[A-F]"
)


def _detect_freetext_intake_skip(messages: list[str]) -> bool:
    user_turns = [
        m.strip()
        for m in messages
        if m.strip() and not m.startswith("[位置上下文]") and not INTAKE_SUBMISSION_RE.search(m)
    ]
    if len(user_turns) < 2:
        return False
    return any(len(m) >= 6 and FREETEXT_INTAKE_HINTS.search(m) for m in user_turns[1:])


def parse_slots_from_messages(messages: list[str]) -> Slots:
    slots = Slots(user_messages=list(messages))
    blob = "\n".join(messages)

    if INTAKE_SUBMISSION_RE.search(blob):
        slots.intake_submitted = True
        slots.intake_consumed = True
        slots.intake_mode = "formal"
        slots.ready = True

    if re.search(r"全部用默认|直接回复.*默认", blob):
        slots.intake_consumed = True
        slots.intake_mode = "defaults"
        slots.ready = True

    freetext_skip = _detect_freetext_intake_skip(messages)
    if freetext_skip:
        slots.intake_consumed = True
        slots.intake_mode = "skipped_freetext"

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
        # 用统一的 detect_planning_intent（含规划上下文词），修窄正则漏判导致首轮被判闲聊。
        planning_intent = detect_planning_intent(blob)
        if planning_intent and slots.party_size and slots.city:
            slots.ready = True
        if planning_intent and INTAKE_SUBMISSION_RE.search(blob):
            slots.ready = True
        if re.search(r"全部用默认|直接回复.*默认", blob):
            slots.ready = True
        # 用户不点选、用口语回复问卷：视为槽位已提交，允许进入 B 阶段
        if planning_intent and freetext_skip:
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
    t = blob or ""
    if PLANNING_INTENT_RE.search(t):
        return True
    # fail-open：含规划上下文词且有一定信息量（非短问候）也算规划意图，
    # 避免 PLANNING_INTENT_RE 漏判「看展/公园/创意菜/慢慢逛」这类口语诉求被当成闲聊/纯天气。
    if PLANNING_CONTEXT_RE.search(t) and len(t.strip()) >= 10:
        return True
    return False


def detect_light_weather(last_user: str, blob: str = "") -> bool:
    """仅当消息「明确就是纯查天气」时才判 light_weather（fail-open）。

    旧逻辑是 fail-closed：regex 漏判一个规划词就误判纯天气 → 拦死整轮搜点/算路。
    代价不对称——误把规划判成纯天气会让用户看到「实时查询不可用」；反之只是多搜一次。
    故改为：本条/整段只要带任何规划意图或规划上下文词、或消息过长，就不降级。
    """
    t = (last_user or "").strip()
    if not t or not WEATHER_ONLY_RE.search(t):
        return False
    if detect_planning_intent(t) or PLANNING_CONTEXT_RE.search(t):
        return False
    if detect_planning_intent(blob) or PLANNING_CONTEXT_RE.search(blob):
        return False
    # 纯天气问句通常很短；过长基本是混合诉求 → 放行规划
    if len(t) > 40:
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
