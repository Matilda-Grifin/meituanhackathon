#!/usr/bin/env python3
"""按赛题维度对单条 case 计算 0-100 分项分与加权总分。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from intake_simulator import has_intake_pattern
from rubric_context import find_unconfirmed_party_in_reply, infer_context

_BENCH = Path(__file__).resolve().parent

_FOOD = re.compile(r"餐|吃|饭|小吃|咖啡|火锅|米线和|菜馆|餐厅")
_PLAY = re.compile(r"博物|展览|美术馆|公园|逛|玩|娱乐|西湖|步行|动线|景点")
_TIME = re.compile(r"\d{1,2}:\d{2}|时段|上午|下午|晚上|小时")
_LINK = re.compile(r"amap\.com|https?://")
_ROUTE = re.compile(r"\d+\s*分钟|公里|驾车|步行|地铁|打车")


def load_score_config(path: Path | None = None) -> dict:
    p = path or _BENCH / "score_dimensions.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _score_first_response(pred: dict, ctx) -> tuple[int, str]:
    turns = pred.get("turns") or []
    if not turns:
        return 50, "no_turn_data"
    t0 = turns[0]
    ms = t0.get("time_to_first_assistant_text_ms") or t0.get("time_to_first_progress_ms")
    has_text = bool((t0.get("assistant_text") or "").strip())
    has_tool = bool(t0.get("tools"))
    if ms is None:
        if ctx.get("slots_incomplete") and has_intake_pattern(t0.get("assistant_text") or ""):
            return 85, "intake_visible_no_timing"
        if has_text or has_tool:
            return 75, "progress_no_timing"
        return 40, "no_visible_progress"
    ms = float(ms)
    if ms <= 10000:
        return 100, f"ttft_ms={int(ms)}"
    if ms <= 15000:
        return 70, f"ttft_ms={int(ms)}"
    if ms <= 25000:
        return 40, f"ttft_ms={int(ms)}"
    return 10, f"ttft_ms={int(ms)}"


def _score_intake(pred: dict, ctx, rule_results: list[dict]) -> tuple[int, str]:
    if not ctx.get("slots_incomplete"):
        return 100, "slots_already_complete"
    first = str(pred.get("first_assistant_text") or "")
    if not first and pred.get("turns"):
        first = str((pred["turns"][0] or {}).get("assistant_text") or "")
    if has_intake_pattern(first):
        return 100, "first_turn_intake_ok"
    for r in rule_results:
        if r.get("rule_id") == "must_intake_first_turn":
            return 0 if not r.get("pass") else 100, r.get("detail", "")
    return 20, "missing_intake"


def _score_tools(tools_fw: list[dict]) -> tuple[int, str]:
    if not tools_fw:
        return 70, "no_framework_applied"
    scores = []
    notes = []
    for fw in tools_fw:
        n = len(fw.get("expected_tool_roles") or [])
        h = len(fw.get("roles_hit") or [])
        if n == 0:
            continue
        scores.append(100.0 * h / n)
        notes.append(f"{fw.get('framework')}:{h}/{n}")
    if not scores:
        return 70, "no_tool_framework"
    avg = sum(scores) / len(scores)
    return int(round(avg)), ";".join(notes)


def _score_honesty(pred: dict, ctx) -> tuple[int, str]:
    if not ctx.get("party_size_not_given"):
        return 100, "party_given_by_user"
    hits = find_unconfirmed_party_in_reply(str(pred.get("assistant_text") or ""))
    if hits:
        return 0, f"preset_party:{hits}"
    return 100, "ok"


def _score_plan_completeness(pred: dict, ctx) -> tuple[int, str]:
    if not ctx.get("planning_intent") or ctx.get("weather_primary"):
        return 100, "not_plan_case"
    text = str(pred.get("assistant_text") or "")
    if len(text) < 80:
        return 20, "reply_too_short"
    has_food = bool(_FOOD.search(text))
    has_play = bool(_PLAY.search(text))
    has_time = bool(_TIME.search(text))
    poi_hints = len(re.findall(r"店|馆|广场|公园|博物|咖啡|米", text))
    score = 0
    if has_food:
        score += 35
    if has_play:
        score += 35
    if has_time:
        score += 15
    if poi_hints >= 2:
        score += 15
    score = min(100, score)
    return score, f"food={has_food},play={has_play},time={has_time},poi_hints={poi_hints}"


def _score_executability(pred: dict, ctx) -> tuple[int, str]:
    if not ctx.get("planning_intent") or ctx.get("weather_primary"):
        return 100, "not_plan_case"
    text = str(pred.get("assistant_text") or "")
    score = 30
    notes = []
    if _LINK.search(text):
        score += 35
        notes.append("links")
    if _ROUTE.search(text):
        score += 25
        notes.append("route_minutes")
    if re.search(r"天气|气温|℃|降水", text):
        score += 10
        notes.append("weather_cited")
    return min(100, score), ",".join(notes) or "minimal"


def compute_dimension_scores(
    case: dict,
    pred: dict,
    ctx,
    rule_results: list[dict],
    tools_fw: list[dict],
    config: dict | None = None,
) -> dict[str, Any]:
    config = config or load_score_config()
    users = list(pred.get("user_messages") or [case.get("user_text", "")])
    if ctx is None:
        ctx = infer_context(users)

    scorers = {
        "first_response": lambda: _score_first_response(pred, ctx),
        "intake_flow": lambda: _score_intake(pred, ctx, rule_results),
        "tool_execution": lambda: _score_tools(tools_fw),
        "constraint_honesty": lambda: _score_honesty(pred, ctx),
        "plan_completeness": lambda: _score_plan_completeness(pred, ctx),
        "executability": lambda: _score_executability(pred, ctx),
    }

    dims_out = []
    total_w = 0.0
    weighted = 0.0
    for d in config.get("dimensions") or []:
        did = d["id"]
        w = float(d.get("weight", 0))
        fn = scorers.get(did)
        if not fn:
            continue
        score, note = fn()
        dims_out.append(
            {
                "id": did,
                "name": d.get("name"),
                "weight": w,
                "score": score,
                "note": note,
                "source": d.get("source"),
            }
        )
        total_w += w
        weighted += w * score

    total = int(round(weighted / total_w)) if total_w else 0
    threshold = int(config.get("pass_threshold", 60))
    return {
        "dimension_scores": dims_out,
        "total_score": total,
        "pass_threshold": threshold,
        "pass_by_score": total >= threshold,
    }
