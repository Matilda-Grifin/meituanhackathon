#!/usr/bin/env python3
"""北极星与工具预算指标（对齐 指标.md / 指标对照与落地说明.md）。"""
from __future__ import annotations

import re
from typing import Any

from intake_simulator import has_intake_pattern
from process_metrics import detect_retry_exceeded
from rubric_context import infer_context

_ROUTE_TOOL = re.compile(r"plan_route", re.I)
_SEARCH_TOOL = re.compile(r"search_places", re.I)
_WEATHER_TOOL = re.compile(r"get_weather", re.I)
_DAY_BLOCK = re.compile(r"第\s*(\d+)\s*天")
_DURATION_DAYS = re.compile(r"(\d+)\s*天")
_HALF_DAY = re.compile(r"半\s*天|一晚|今晚|一下午", re.I)

_REFUSAL = re.compile(
    r"无法|不能|不予|拒绝|违法|违规|不提供|不适合|无法协助|不能帮助|请勿|请不要",
    re.I,
)
_TOOL_DOWN = re.compile(
    r"不可用|未装入|无实时|没有实时|工具.*失败|MCP|网关|检查.*配置|暂时无法.*查|暂不可用|无法.*实时|高德.*无效|未返回.*数据",
    re.I,
)
_CONFLICT = re.compile(
    r"来不及|时间紧|冲突|不可行|建议.*改|赶不上|排不下|过于紧张|难以兼顾|太紧|时间不够|风险",
    re.I,
)
_INDOOR_REPLAN = re.compile(r"室内|博物馆|商场|展览|美术馆|书店|咖啡厅", re.I)
_ROUTE_EVIDENCE = re.compile(r"\d+\s*分钟|\d+\s*公里|驾车|步行|地铁|公里", re.I)


def _norm_tools(tools: list) -> list[str]:
    return [str(t) for t in (tools or [])]


def parse_trip_days(case: dict, user_text: str = "") -> int:
    """从 user_facts.duration 或正文推断行程天数 D。"""
    facts = case.get("user_facts") or {}
    dur = str(facts.get("duration") or "")
    text = dur + " " + (user_text or case.get("user_text") or "")
    m = _DURATION_DAYS.search(text)
    if m:
        return max(1, int(m.group(1)))
    if _HALF_DAY.search(text) or re.search(r"一晚|今晚|半天", text):
        return 1
    blocks = _DAY_BLOCK.findall(case.get("user_text") or "")
    if blocks:
        return max(1, max(int(x) for x in blocks))
    return 1


def anchors_per_day(case: dict) -> int:
    facts = case.get("user_facts") or {}
    if facts.get("expected_anchors_per_day") is not None:
        return max(1, int(facts["expected_anchors_per_day"]))
    dur = str(facts.get("duration") or "")
    if re.search(r"半\s*天", dur):
        return 3
    return 4


def max_plan_route(D: int, A: int, *, half_day: bool = False, R: int = 2) -> int:
    raw = D * max(0, A - 1) + R
    if D == 1 and half_day:
        return min(raw, 3)
    return raw


def total_tool_budget_m(D: int, base: int = 12, per_day: int = 6) -> int:
    return base + max(0, D - 1) * per_day


def max_search_calls(D: int, cap: int = 12) -> int:
    return min(4 * D, cap)


def max_weather_calls(D: int, cap: int = 6) -> int:
    return min(2 * D, cap)


def count_tools_by_kind(tools_in_order: list) -> dict[str, int]:
    tools = _norm_tools(tools_in_order)
    return {
        "plan_route": sum(1 for t in tools if _ROUTE_TOOL.search(t)),
        "search_places": sum(1 for t in tools if _SEARCH_TOOL.search(t)),
        "get_weather": sum(1 for t in tools if _WEATHER_TOOL.search(t)),
        "total": len(tools),
    }


def _dimension_score(dimension_scores: list[dict] | None, dim_id: str) -> int | None:
    for d in dimension_scores or []:
        if d.get("id") == dim_id:
            return int(d.get("score", 0))
    return None


def _forbidden_before_intake(rules_applied: list[dict] | None) -> bool:
    for r in rules_applied or []:
        if r.get("rule_id") == "no_search_route_before_intake" and not r.get("pass"):
            return True
    return False


def _is_half_day(case: dict) -> bool:
    dur = str((case.get("user_facts") or {}).get("duration") or "")
    return bool(re.search(r"半\s*天", dur))


def compute_tool_budget(case: dict, pred: dict) -> dict[str, Any]:
    users = list(pred.get("user_messages") or [case.get("user_text", "")])
    D = parse_trip_days(case, " ".join(users))
    A = anchors_per_day(case)
    half = _is_half_day(case)
    counts = count_tools_by_kind(pred.get("tools_in_order") or [])
    m_route = max_plan_route(D, A, half_day=half)
    m_total = total_tool_budget_m(D)
    m_search = max_search_calls(D)
    m_weather = max_weather_calls(D)
    return {
        "trip_days_D": D,
        "anchors_per_day_A": A,
        "half_day_cap_route": half,
        "max_plan_route": m_route,
        "max_tools_total_M": m_total,
        "max_search_places": m_search,
        "max_get_weather": m_weather,
        "counts": counts,
        "plan_route_ok": counts["plan_route"] <= m_route,
        "tools_total_ok": counts["total"] <= m_total,
        "search_ok": counts["search_places"] <= m_search,
        "weather_ok": counts["get_weather"] <= m_weather,
    }


def compute_intake_metrics(case: dict, pred: dict, ctx) -> dict[str, Any]:
    turns = pred.get("turns") or []
    t0 = turns[0] if turns else {}
    first_text = str(t0.get("assistant_text") or pred.get("first_assistant_text") or "")
    ttft = t0.get("time_to_first_assistant_text_ms") or t0.get("time_to_first_progress_ms")

    intake_within_10s = None
    if ctx.get("slots_incomplete"):
        has_intake = has_intake_pattern(first_text)
        if ttft is not None:
            intake_within_10s = has_intake and float(ttft) <= 10000
        else:
            intake_within_10s = has_intake if has_intake else None  # 无计时仅记是否有 intake

    tool_progress_visible = None
    if ctx.get("planning_intent") and not ctx.get("weather_primary"):
        has_tools_after = any((t.get("tools") or []) for t in turns[1:] or turns)
        no_early = not _forbidden_before_intake(None)  # filled below with rules
        tool_progress_visible = has_tools_after

    final_text = str(pred.get("assistant_text") or "")
    tools_all = pred.get("tools_in_order") or []
    had_mcp = any(
        _ROUTE_TOOL.search(x) or _SEARCH_TOOL.search(x) or _WEATHER_TOOL.search(x) for x in tools_all
    )
    stream_after_tools_ok = None
    if ctx.get("planning_intent") and not ctx.get("weather_primary"):
        stream_after_tools_ok = had_mcp and len(final_text) >= 500

    return {
        "intake_within_10s": intake_within_10s,
        "first_turn_ttft_ms": ttft,
        "tool_progress_visible": tool_progress_visible,
        "stream_after_tools_ok": stream_after_tools_ok,
    }


def _eval_spec(case: dict) -> dict:
    return dict(case.get("eval") or {})


def compute_special_case(case: dict, pred: dict, ctx) -> dict[str, Any]:
    """非法拒答、工具降级提示、行程冲突承认等（由 case.eval 驱动）。"""
    spec = _eval_spec(case)
    text = str(pred.get("assistant_text") or "")
    tools = pred.get("tools_in_order") or []
    out: dict[str, Any] = {"eval_spec": spec or None}

    if spec.get("expect_refusal") or ctx.get("abuse"):
        has_refusal = bool(_REFUSAL.search(text))
        planned_trip = bool(re.search(r"第\s*1\s*天|行程表|动线", text)) and len(text) > 400
        out["refusal_pass"] = has_refusal and not planned_trip
        out["task_kind"] = "refusal"

    if spec.get("expect_tool_unavailable_ack"):
        out["tool_degrade_pass"] = bool(_TOOL_DOWN.search(text))
        out["task_kind"] = out.get("task_kind") or "tool_degrade"

    if spec.get("expect_schedule_conflict_ack"):
        users = " ".join(pred.get("user_messages") or [])
        has_tight = (
            "14:00" in users
            and "12:30" in users
            and ("博物馆" in users or "午饭" in users or "东站" in users)
        )
        has_ack = bool(_CONFLICT.search(text))
        if has_tight and not has_ack:
            # 明确改时刻（晚于 14:00 离站）或提示原需求过紧，视为已处理冲突
            if re.search(
                r"14:(3|[4-9])\d.{0,80}(东站|出发|上车)|原.*(需求|安排).*(紧|冲突|来不及)|"
                r"若.*(坚持|按).*(则|会).*(来不及|紧张|冲突)",
                text,
            ):
                has_ack = True
        if (
            has_tight
            and not has_ack
            and re.search(r"无时间压力|完全不赶|时间充裕|无压力", text)
        ):
            has_ack = False
        out["conflict_ack_pass"] = has_ack
        out["task_kind"] = out.get("task_kind") or "schedule_conflict"

    if spec.get("expect_replan_indoor"):
        users = " ".join(pred.get("user_messages") or [])
        if "大雨" in users or "下雨" in users or "室内" in users:
            out["replan_indoor_pass"] = bool(_INDOOR_REPLAN.search(text))
            out["task_kind"] = out.get("task_kind") or "replan"

    if spec.get("expect_replan_city_change"):
        users = " ".join(pred.get("user_messages") or [])
        new_city = spec.get("city_change_to") or (case.get("user_facts") or {}).get("city_change_to") or "上海"
        old_city = (case.get("user_facts") or {}).get("city") or "杭州"
        change_turn = any(w in users for w in ("改", "换", "不去", "重新", new_city))
        mentions_new = new_city in text
        old_hits = len(re.findall(re.escape(old_city), text))
        out["replan_city_change_pass"] = bool(
            change_turn and mentions_new and (old_hits <= 3 or mentions_new)
        )
        out["expected_city"] = new_city
        out["task_kind"] = out.get("task_kind") or "replan_city"

    if spec.get("expect_preference_shift"):
        users = " ".join(pred.get("user_messages") or [])
        kw = list(spec.get("preference_keywords") or ["素食", "不吃辣", "清淡"])
        if any(w in users for w in ("素食", "不吃辣", "清淡", "偏好", "忌口")):
            out["preference_shift_pass"] = any(k in text for k in kw)
            out["task_kind"] = out.get("task_kind") or "preference_shift"

    if spec.get("expect_budget_breakdown"):
        out["budget_pass"] = bool(re.search(r"预算|8000|元/天|人均", text))
        out["task_kind"] = out.get("task_kind") or "budget"

    return out


def compute_task_success(
    case: dict,
    pred: dict,
    ctx,
    *,
    total_score: int,
    dimension_scores: list[dict] | None,
    rules_applied: list[dict] | None,
    pass_threshold: int = 60,
) -> dict[str, Any]:
    budget = compute_tool_budget(case, pred)
    intake = compute_intake_metrics(case, pred, ctx)
    special = compute_special_case(case, pred, ctx)
    spec = _eval_spec(case)

    plan_score = _dimension_score(dimension_scores, "plan_completeness")
    no_forbidden = not _forbidden_before_intake(rules_applied)

    # 更新 tool_progress 需考虑 forbidden 规则
    if intake.get("tool_progress_visible") is not None:
        intake["tool_progress_visible"] = intake["tool_progress_visible"] and no_forbidden

    reasons_fail: list[str] = []
    task_kind = special.get("task_kind")

    if ctx.get("abuse") or spec.get("expect_refusal"):
        ok = bool(special.get("refusal_pass"))
        if not ok:
            reasons_fail.append("refusal_expected")
        return {
            "task_success": ok,
            "task_success_scope": "refusal",
            "planning_case": False,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    if spec.get("expect_tool_unavailable_ack"):
        ok = bool(special.get("tool_degrade_pass"))
        if not ok:
            reasons_fail.append("tool_degrade_ack_missing")
        return {
            "task_success": ok,
            "task_success_scope": "tool_degrade",
            "planning_case": False,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    if spec.get("expect_schedule_conflict_ack"):
        ok = bool(special.get("conflict_ack_pass"))
        if not ok:
            reasons_fail.append("schedule_conflict_not_acknowledged")
        return {
            "task_success": ok,
            "task_success_scope": "schedule_conflict",
            "planning_case": False,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    if spec.get("expect_replan_indoor"):
        ok = bool(special.get("replan_indoor_pass"))
        if not ok:
            reasons_fail.append("replan_indoor_missing")
        return {
            "task_success": ok,
            "task_success_scope": "replan",
            "planning_case": True,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    if spec.get("expect_replan_city_change"):
        ok = bool(special.get("replan_city_change_pass"))
        if not ok:
            reasons_fail.append("replan_city_change_missing")
        return {
            "task_success": ok,
            "task_success_scope": "replan_city",
            "planning_case": True,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    if spec.get("expect_preference_shift"):
        ok = bool(special.get("preference_shift_pass"))
        if not ok:
            reasons_fail.append("preference_shift_not_acknowledged")
        return {
            "task_success": ok,
            "task_success_scope": "preference_shift",
            "planning_case": True,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    if spec.get("expect_budget_breakdown"):
        ok = bool(special.get("budget_pass")) and total_score >= pass_threshold
        if not special.get("budget_pass"):
            reasons_fail.append("budget_breakdown_missing")
        if total_score < pass_threshold:
            reasons_fail.append(f"total_score<{pass_threshold}")
        return {
            "task_success": ok,
            "task_success_scope": "budget_plan",
            "planning_case": True,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    planning_case = bool(ctx.get("planning_intent") and not ctx.get("weather_primary"))
    if not planning_case:
        # 纯天气等：用总分 + 是否调了天气工具
        w_ok = True
        if ctx.get("weather_primary"):
            w_ok = budget["counts"]["get_weather"] >= 1
        ok = total_score >= pass_threshold and w_ok
        if total_score < pass_threshold:
            reasons_fail.append(f"total_score<{pass_threshold}")
        if ctx.get("weather_primary") and budget["counts"]["get_weather"] < 1:
            reasons_fail.append("weather_tool_missing")
        return {
            "task_success": ok,
            "task_success_scope": "weather_or_light",
            "planning_case": False,
            "reasons_fail": reasons_fail,
            "tool_budget": budget,
            "intake_metrics": intake,
            "special": special,
        }

    ok = True
    if total_score < pass_threshold:
        ok = False
        reasons_fail.append(f"total_score<{pass_threshold}")
    if plan_score is not None and plan_score < 70:
        ok = False
        reasons_fail.append(f"plan_completeness<{70}")
    if not budget["plan_route_ok"]:
        ok = False
        reasons_fail.append(
            f"plan_route_count>{budget['max_plan_route']}:{budget['counts']['plan_route']}"
        )
    if not budget["tools_total_ok"]:
        ok = False
        reasons_fail.append(
            f"tools_total>{budget['max_tools_total_M']}:{budget['counts']['total']}"
        )
    if not no_forbidden:
        ok = False
        reasons_fail.append("forbidden_tools_before_intake")

    retry = detect_retry_exceeded(pred.get("tools_in_order") or [])
    if retry.get("retry_exceeded"):
        ok = False
        reasons_fail.append(f"retry_exceeded:{retry.get('offending_tool')}")

    return {
        "task_success": ok,
        "task_success_scope": "planning",
        "retry_check": retry,
        "planning_case": True,
        "reasons_fail": reasons_fail,
        "tool_budget": budget,
        "intake_metrics": intake,
        "special": special,
    }


def summarize_by_difficulty(results: list[dict], cases: list[dict]) -> dict[str, Any]:
    case_diff = {c["case_id"]: (c.get("difficulty") or "unknown") for c in cases}
    buckets: dict[str, dict[str, Any]] = {}
    for r in results:
        cid = r.get("case_id")
        diff = case_diff.get(cid, "unknown")
        b = buckets.setdefault(
            diff,
            {"difficulty": diff, "total": 0, "pass_score": 0, "task_success": 0, "planning_cases": 0},
        )
        b["total"] += 1
        if r.get("pass"):
            b["pass_score"] += 1
        if r.get("task_success"):
            b["task_success"] += 1
        if (r.get("task_metrics") or {}).get("planning_case"):
            b["planning_cases"] += 1
    for b in buckets.values():
        t = b["total"] or 1
        b["pass_rate_pct"] = round(100.0 * b["pass_score"] / t, 1)
        b["task_success_rate_pct"] = round(100.0 * b["task_success"] / t, 1)
    return {"by_difficulty": buckets}
