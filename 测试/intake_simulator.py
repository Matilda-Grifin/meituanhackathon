#!/usr/bin/env python3
"""解析 Agent intake 选择题，并生成可审计的模拟用户回复。"""
from __future__ import annotations

import re
from typing import Any


def has_intake_pattern(text: str) -> bool:
    t = text or ""
    if re.search(r"\*\*[A-D]\.\*\*", t, re.I):
        return True
    if re.search(r"\*\*[A-D]\.\s*", t, re.I):
        return True
    if re.search(r"第\s*[123]\s*题", t):
        return True
    if re.search(r"(?m)^\s*[A-D][\.、．]\s", t):
        return len(re.findall(r"(?m)^\s*[A-D][\.、．]", t)) >= 2
    return False


def looks_like_plan_without_intake(text: str) -> bool:
    """Agent 直接给行程、未反问。"""
    t = text or ""
    if has_intake_pattern(t):
        return False
    markers = ("### ", "## ", "行程", "推荐", "19:00", "20:00", "第一站", "动线")
    return any(m in t for m in markers) and len(t) > 120


def extract_intake_prompt_excerpt(text: str, max_len: int = 800) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def parse_option_letters(text: str) -> list[str]:
    """从助手消息里粗略提取出现过的选项字母。"""
    found: list[str] = []
    for m in re.finditer(r"\*\*([A-D])\.\*\*", text, re.I):
        found.append(m.group(1).upper())
    for m in re.finditer(r"(?m)^\s*\*\*([A-D])\.\s", text, re.I):
        found.append(m.group(1).upper())
    for m in re.finditer(r"(?m)^\s*([A-D])[\.、．]", text, re.I):
        found.append(m.group(1).upper())
    return list(dict.fromkeys(found))


def format_user_facts(facts: dict[str, Any]) -> str:
    """把 user_facts 转成给 LLM / 脚本的「用户已知信息」说明（不是 A/B/C 答案）。"""
    if not facts:
        return ""
    if facts.get("use_defaults"):
        return "用户选择全部默认：城市默认坐标、半天、2成人、不忌口、交通地铁+打车。"

    lines: list[str] = []
    mapping = [
        ("scene", "场景"),
        ("party_size", "人数"),
        ("party_detail", "同行"),
        ("child_age", "孩子年龄"),
        ("city", "城市"),
        ("district", "区域"),
        ("landmark", "地标/附近"),
        ("time", "时段"),
        ("duration", "时长"),
        ("transport", "交通"),
        ("diet", "饮食偏好"),
        ("activity", "想做的事"),
        ("extra", "补充"),
    ]
    for key, label in mapping:
        val = facts.get(key)
        if val is not None and str(val).strip():
            lines.append(f"{label}：{val}")
    must_not = facts.get("must_not_say") or []
    if must_not:
        lines.append("不要说：" + "、".join(str(x) for x in must_not))
    return "；".join(lines)


def _add_intake_option(block: dict, letter: str, text: str) -> None:
    letter = letter.upper()
    text = (text or "").strip()
    if not text:
        return
    for o in block["options"]:
        if o["letter"] == letter:
            return
    block["options"].append({"letter": letter, "text": text})


def parse_intake_blocks(text: str) -> list[dict[str, Any]]:
    """解析助手消息中的编号选择题（与 gateway-chat-ui 逻辑对齐）。"""
    by_n: dict[int, dict[str, Any]] = {}
    cur_n = 0

    def cur_block() -> dict[str, Any] | None:
        if cur_n <= 0:
            return None
        if cur_n not in by_n:
            by_n[cur_n] = {"n": cur_n, "title": "", "options": []}
        return by_n[cur_n]

    for raw in (text or "").split("\n"):
        line = raw.strip()
        q_head = re.match(r"^(\d+)(?:[\.、．]|\)|）)\s*(.*)$", line)
        if q_head:
            cur_n = int(q_head.group(1))
            rest = (q_head.group(2) or "").strip()
            b = cur_block()
            if b and rest:
                b["title"] = rest
            for m in re.finditer(r"\*\*([A-D])\.\*\*\s*(.+)", rest, re.I):
                _add_intake_option(b, m.group(1), m.group(2))
            continue
        b = cur_block()
        if not b:
            continue
        for m in re.finditer(r"\*\*([A-D])\.\*\*\s*(.+)", line, re.I):
            _add_intake_option(b, m.group(1), m.group(2))
        for m in re.finditer(r"^\s*([A-D])(?:[\.、．]|\)|）|：)\s*(.+)$", line, re.I):
            _add_intake_option(b, m.group(1), m.group(2))

    return sorted(
        [b for b in by_n.values() if b.get("options")],
        key=lambda x: x["n"],
    )


def _classify_question(title: str, options: list[dict]) -> str:
    blob = title + " " + " ".join(o["text"] for o in options)
    rules = [
        ("scene_ambiguous", r"老婆孩子\s*/\s*朋友|家人.*朋友"),
        ("scene", r"家庭|亲子|带娃|朋友局|和朋友|情侣"),
        ("party", r"人数|几个人|总人数|同行|一共"),
        ("child_age", r"孩子.*年龄|几岁|幼儿|学前"),
        ("child_config", r"成人.*孩子|几大几小|1位成人"),
        ("activity", r"活动|类型|倾向|想吃|逛|玩什么"),
        ("museum", r"博物馆|展览|手工|亲子互动"),
        ("transport", r"交通|出行|地铁|自驾|打车|公交|步行"),
        ("diet", r"口味|忌口|饮食|清淡|辣"),
        ("duration", r"时长|半天|一天|多久"),
        ("district", r"哪个区|所在区|出发|从哪"),
        ("time", r"时段|什么时候|今晚|下午|上午"),
        ("arrival", r"高铁|火车|飞机|到达|机场|车站"),
    ]
    for name, pat in rules:
        if re.search(pat, blob, re.I):
            return name
    return "generic"


def _score_option(text: str, keywords: list[str]) -> int:
    t = text.lower()
    return sum(1 for k in keywords if k and k.lower() in t)


def _pick_party_option(options: list[dict], facts: dict[str, Any]) -> tuple[str, str]:
    size = facts.get("party_size")
    detail = str(facts.get("party_detail") or "")
    if size is None and detail:
        m = re.search(r"(\d+)\s*人|2\s*大\s*1\s*小|1\s*大\s*1\s*小", detail)
        if m:
            if "大" in detail and "小" in detail:
                return _pick_by_keywords(
                    options,
                    ["1位成人+1位孩子", "2位成人+1位孩子", "2大1小", "1大1小"],
                    fallback_letter="A",
                )[0], detail
            size = int(m.group(1))
    if size is not None:
        for o in options:
            nums = re.findall(r"(\d+)\s*人", o["text"])
            if nums and int(nums[0]) == int(size):
                return o["letter"], ""
        for o in options:
            if str(size) in o["text"]:
                return o["letter"], ""
    if "2大1小" in detail or "1大1小" in detail:
        letter, _ = _pick_by_keywords(
            options,
            ["2位成人+1位孩子", "1位成人+1位孩子", "2大", "1大"],
            fallback_letter="A",
        )
        return letter, detail
    return "D", detail or (f"一共{size}人" if size else "")


def _pick_by_keywords(
    options: list[dict],
    keywords: list[str],
    *,
    fallback_letter: str = "A",
    avoid: list[str] | None = None,
) -> tuple[str, str]:
    avoid = avoid or []
    best_l, best_s = fallback_letter, -1
    for o in options:
        if any(a in o["text"] for a in avoid):
            continue
        s = _score_option(o["text"], keywords)
        if s > best_s:
            best_s, best_l = s, o["letter"]
    if best_s > 0:
        return best_l, ""
    d = next((o for o in options if o["letter"] == "D"), None)
    if d and ("其他" in d["text"] or "自填" in d["text"] or "说明" in d["text"]):
        return "D", "；".join(keywords[:3])
    return fallback_letter, ""


def _pick_option_for_block(block: dict, facts: dict[str, Any]) -> tuple[str, str]:
    title = block.get("title") or ""
    options = block.get("options") or []
    if not options:
        return "A", ""
    slot = _classify_question(title, options)
    overrides = facts.get("choice_overrides") or {}
    if str(block["n"]) in overrides:
        return str(overrides[str(block["n"])]).upper(), facts.get("other_note") or ""
    if overrides.get(slot):
        return str(overrides[slot]).upper(), facts.get("other_note") or ""

    if slot == "scene_ambiguous":
        if facts.get("scene") == "朋友" or "朋友" in str(facts.get("party_detail") or ""):
            return _pick_by_keywords(options, ["朋友", "同学", "聚会"], avoid=["老婆", "孩子", "亲子"])
        if facts.get("scene") == "家庭":
            return _pick_by_keywords(options, ["家庭", "老婆", "孩子", "亲子", "带娃"])
        return _pick_by_keywords(options, ["朋友"], fallback_letter="B")

    if slot in ("party", "child_config"):
        return _pick_party_option(options, facts)

    if slot == "child_age":
        age = facts.get("child_age")
        if age is not None:
            for o in options:
                nums = [int(x) for x in re.findall(r"(\d+)", o["text"])]
                if len(nums) >= 2 and nums[0] <= int(age) <= nums[-1]:
                    return o["letter"], ""
                if str(age) in o["text"]:
                    return o["letter"], ""
        return _pick_by_keywords(options, ["4-6", "4", "5", "6", "学前"], fallback_letter="B")

    if slot in ("activity", "museum"):
        act = str(facts.get("activity") or "")
        keys = re.findall(r"[\u4e00-\u9fff]{2,}", act) + [act]
        return _pick_by_keywords(options, keys + ["博物馆", "展览", "咖啡", "火锅", "公园", "商圈", "夜宵", "小吃", "商场"])

    if slot == "transport":
        tr = str(facts.get("transport") or "")
        return _pick_by_keywords(
            options,
            re.findall(r"[\u4e00-\u9fff]{2,}", tr) + [tr, "地铁", "自驾", "打车", "公交", "步行"],
        )

    if slot == "diet":
        diet = str(facts.get("diet") or "")
        return _pick_by_keywords(options, [diet, "清淡", "低油", "减肥", "微辣", "不辣", "不忌口"])

    if slot == "duration":
        dur = str(facts.get("duration") or "")
        return _pick_by_keywords(options, [dur, "半天", "一天", "几小时"])

    if slot == "district":
        dist = str(facts.get("district") or facts.get("current_location") or "")
        city = str(facts.get("city") or "")
        letter, _ = _pick_by_keywords(options, [dist, city, facts.get("landmark") or ""])
        if _score_option(next(o["text"] for o in options if o["letter"] == letter), [dist]) > 0:
            return letter, ""
        return "D", dist or facts.get("landmark") or ""

    if slot == "time":
        tm = str(facts.get("time") or "")
        return _pick_by_keywords(options, [tm, "今晚", "下午", "上午", "明天"])

    if slot == "scene":
        sc = str(facts.get("scene") or "")
        return _pick_by_keywords(options, [sc, "家庭", "朋友", "情侣", "亲子"])

    return _pick_by_keywords(options, [str(facts.get("activity") or ""), str(facts.get("extra") or "")])


def resolve_choices_from_assistant(assistant_text: str, facts: dict[str, Any]) -> tuple[dict[str, str], str]:
    """根据助手本轮选择题 + case user_facts，解析每题应选字母。"""
    if facts.get("use_defaults"):
        return {}, ""
    blocks = parse_intake_blocks(assistant_text)
    if not blocks:
        return {}, ""
    choices: dict[str, str] = {}
    notes: list[str] = []
    for block in blocks:
        letter, note = _pick_option_for_block(block, facts)
        choices[str(block["n"])] = letter
        if note:
            notes.append(note)
    other = (facts.get("other_note") or "").strip()
    if other:
        notes.append(other)
    return choices, "；".join(dict.fromkeys(notes))


def build_reply_from_user_facts(facts: dict[str, Any]) -> str:
    """无 LLM 时：用口语复述 user_facts（不编造「第N题选X」）。"""
    if facts.get("use_defaults"):
        return "全部用默认（城市默认坐标、半天、2成人、不忌口、地铁+打车）"
    parts: list[str] = []
    if facts.get("party_detail"):
        parts.append(str(facts["party_detail"]))
    elif facts.get("party_size"):
        parts.append(f"一共{facts['party_size']}人")
    if facts.get("child_age"):
        parts.append(f"孩子{facts['child_age']}岁")
    if facts.get("city"):
        parts.append(f"在{facts['city']}")
    if facts.get("district"):
        parts.append(str(facts["district"]))
    if facts.get("landmark"):
        parts.append(f"想在{facts['landmark']}附近")
    if facts.get("time"):
        parts.append(str(facts["time"]))
    if facts.get("duration"):
        parts.append(str(facts["duration"]))
    if facts.get("transport"):
        parts.append(f"交通{facts['transport']}")
    if facts.get("diet"):
        parts.append(str(facts["diet"]))
    if facts.get("activity"):
        parts.append(str(facts["activity"]))
    if facts.get("extra"):
        parts.append(str(facts["extra"]))
    if not parts:
        return format_user_facts(facts)
    return "，".join(parts) + "。"


def build_simulated_user_reply(spec: dict[str, Any], *, assistant_text: str = "") -> str:
    """
    优先 user_message；有 intake 题且带 user_facts 时，按 facts 自动选 A/B/C/D（Web 提交格式）。
    """
    if spec.get("user_message"):
        return str(spec["user_message"])
    facts = spec.get("user_facts") or {}
    if facts.get("use_defaults"):
        return "全部用默认（城市默认坐标、半天、2成人、不忌口、地铁+打车）"
    if assistant_text and has_intake_pattern(assistant_text) and facts:
        choices, note = resolve_choices_from_assistant(assistant_text, facts)
        if choices:
            spec = {**spec, "choices": choices, "other_note": note}
    elif spec.get("choices"):
        pass
    elif facts:
        return build_reply_from_user_facts(facts)
    choices = spec.get("choices") or {}
    if choices:
        parts: list[str] = []
        for key in sorted(choices.keys(), key=lambda x: int(re.sub(r"\D", "", x) or "0")):
            letter = str(choices[key]).upper().strip()
            qn = re.sub(r"\D", "", str(key)) or str(key)
            parts.append(f"第{qn}题选{letter}")
        note = (spec.get("other_note") or spec.get("q3_other") or "").strip()
        body = "选择题答案：" + "；".join(parts)
        if note:
            body += f"；{note}"
        return body
    hint = (spec.get("intent_hint") or "").strip()
    if hint:
        return hint
    return ""


def build_choice_reply(spec: dict[str, Any]) -> str:
    """兼容旧名；请用 build_simulated_user_reply。"""
    return build_simulated_user_reply(spec)


def scripted_reply_for_turn(case: dict, assistant_turn_index: int) -> dict[str, Any] | None:
    """assistant_turn_index: 第几次助手回复之后要模拟用户（1-based）。"""
    sim = case.get("simulation") or {}
    base_facts = case.get("user_facts") or {}
    for row in sim.get("replies") or []:
        if int(row.get("after_assistant_turn", row.get("after_turn", 0))) == assistant_turn_index:
            merged = {**row}
            if base_facts or row.get("user_facts"):
                merged["user_facts"] = {**base_facts, **(row.get("user_facts") or {})}
            return merged
    if assistant_turn_index == 1 and case.get("followup_user") and not sim.get("replies"):
        return {
            "user_message": case["followup_user"],
            "choices": case.get("expected_choices"),
            "note": "legacy followup_user",
        }
    default = sim.get("default_after_intake")
    if default and assistant_turn_index == 1:
        return default
    return None


def audit_entry(
    *,
    case_id: str,
    turn: int,
    assistant_excerpt: str,
    parsed_options: list[str],
    scripted: dict[str, Any],
    user_reply: str,
    reply_source: str = "script",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "turn": turn,
        "assistant_prompt_excerpt": extract_intake_prompt_excerpt(assistant_excerpt),
        "parsed_option_letters": parsed_options,
        "user_facts": scripted.get("user_facts"),
        "resolved_choices": scripted.get("choices"),
        "script_intent_hint": format_user_facts(scripted.get("user_facts") or {})
        or scripted.get("intent_hint")
        or scripted.get("rationale", scripted.get("note", "")),
        "user_reply_sent": user_reply,
        "reply_source": reply_source,
        "expected_match": scripted.get("expected_match"),
    }
