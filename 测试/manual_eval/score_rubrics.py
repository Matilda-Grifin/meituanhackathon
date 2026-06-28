#!/usr/bin/env python3
"""10 Tasks rubric 规则化打分（基于 session jsonl + 前端 eval 日志）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from manual_eval.parse_session import SessionSnapshot, plan_heuristics

INTENT_KEYWORDS = Path(__file__).resolve().parent / "intent_keywords.json"

_RAIL = re.compile(r"高铁|虹桥|火车|站台|误车|缓冲", re.I)
_ACCESS = re.compile(r"无障碍|电梯|台阶|步行|平路|休息", re.I)
_BUDGET_RE = re.compile(r"(\d+)\s*[-~～至到]\s*(\d+)\s*元|人均\s*(\d+)", re.I)
_SPICY = re.compile(r"重辣|辣|串串|小吃", re.I)
_LOW_SUGAR = re.compile(r"低糖|少糖|不吃甜", re.I)
_LOW_OIL = re.compile(r"少油|轻食", re.I)
_LOW_SALT = re.compile(r"少盐|清淡", re.I)

_INTENT_KEYWORDS_CACHE: dict[str, list[str]] | None = None


def _load_intent_keywords() -> dict[str, list[str]]:
    global _INTENT_KEYWORDS_CACHE
    if _INTENT_KEYWORDS_CACHE is not None:
        return _INTENT_KEYWORDS_CACHE
    if INTENT_KEYWORDS.is_file():
        try:
            data = json.loads(INTENT_KEYWORDS.read_text(encoding="utf-8"))
            _INTENT_KEYWORDS_CACHE = data.get("tasks") or {}
            return _INTENT_KEYWORDS_CACHE
        except (json.JSONDecodeError, OSError):
            pass
    _INTENT_KEYWORDS_CACHE = {}
    return _INTENT_KEYWORDS_CACHE


def _intent_keywords(task: dict) -> list[str]:
    tid = str(task.get("id") or "").upper()
    from_file = _load_intent_keywords().get(tid) or []
    if from_file:
        return from_file
    meta = task.get("_meta") or {}
    if isinstance(meta.get("intent_keywords"), list):
        return [str(x) for x in meta["intent_keywords"] if str(x).strip()]
    return []


def _all_rubrics(task: dict) -> list[str]:
    ec = task.get("evaluation_criteria") or {}
    out: list[str] = []
    for block in ec.get("expected_states") or []:
        out.extend(block.get("state_rubrics") or [])
    out.extend(ec.get("overall_rubrics") or [])
    return out


def _budget_from_task(task: dict) -> tuple[int, int] | None:
    text = task.get("instructions") or ""
    m = re.search(r"人均\s*(\d+)\s*[-~～至到]\s*(\d+)\s*元", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    hist = ((task.get("environment") or {}).get("user_historical_behaviors") or {})
    band = str(hist.get("常消费餐饮价格带") or "")
    m2 = re.search(r"(\d+)\s*[-~～至到]\s*(\d+)", band)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    return None


def _score_one_rubric(rubric: str, task: dict, snap: SessionSnapshot, metrics: dict) -> dict:
    t = rubric.strip()
    tl = t.lower()
    plan = snap.final_plan_text or metrics.get("last_assistant_text") or ""
    ph = plan_heuristics(plan)
    tc = snap.tool_counts
    passed = False
    detail = ""

    if "天气" in t:
        passed = tc["weather"] > 0 and (ph["has_weather_mention"] or metrics.get("weather_in_assistant"))
        detail = f"weather_calls={tc['weather']}, plan_mentions_weather={ph['has_weather_mention']} (browser_location: 不限定考卷城市)"
    elif "poi" in tl or "搜索" in t:
        passed = tc["search"] > 0 and ph["poi_hints"] >= 2
        detail = f"search_calls={tc['search']}, poi_hints={ph['poi_hints']}"
    elif "至少3" in t or "3 个" in t or "3个" in t:
        passed = ph["poi_hints"] >= 3 and ph["time_slots"] >= 2
        detail = f"poi_hints={ph['poi_hints']}, time_slots={ph['time_slots']}"
    elif "人均" in t or "预算" in t:
        band = _budget_from_task(task)
        prices = []
        for g in ph["prices"]:
            if g[0] and g[1]:
                prices.append((int(g[0]), int(g[1])))
            elif g[2]:
                prices.append((int(g[2]), int(g[2])))
        if band and prices:
            lo, hi = band
            passed = any(lo <= p[0] <= hi or lo <= p[1] <= hi for p in prices) or (
                str(lo) in plan and str(hi) in plan
            )
            detail = f"expected={band}, prices_in_plan={prices[:3]}"
        else:
            passed = bool(re.search(r"人均|元|预算", plan))
            detail = "budget mentioned in plan (heuristic)"
    elif "40 分钟" in t or "40分钟" in t or "打车" in t and "分钟" in t:
        passed = ph["travel_evidence"] and (re.search(r"[1-3]?\d\s*分钟", plan) or "附近" in plan)
        detail = f"travel_evidence={ph['travel_evidence']}"
    elif "跨区" in t or "同一城市" in t or "均在该城市" in t:
        passed = ph["poi_hints"] >= 3 and ph["time_slots"] >= 3
        detail = "city day trip structure (POI 须落在用户定位城市，不要求考卷原城市名)"
    elif "分时段" in t or "交通" in t or "路程" in t:
        passed = ph["time_slots"] >= 2 and ph["travel_evidence"]
        detail = f"time_slots={ph['time_slots']}, travel={ph['travel_evidence']}"
    elif "高铁" in t or "赶" in t and "车" in t:
        passed = bool(_RAIL.search(plan)) and ph["time_slots"] >= 2
        if "17:30" in t or "缓冲" in t:
            passed = passed and bool(re.search(r"17[:：]|18[:：]|缓冲|预留", plan))
        detail = f"rail_keywords={bool(_RAIL.search(plan))}"
    elif "无障碍" in t or "台阶" in t or "电梯" in t:
        passed = bool(_ACCESS.search(plan)) and ph["poi_hints"] >= 2
        detail = f"access_keywords={bool(_ACCESS.search(plan))}"
    elif "声称结束" in t or "未完成关键约束" in t:
        passed = len(plan) > 300 and ph["poi_hints"] >= 2
        detail = f"plan_len={len(plan)}"
    elif "目标一致" in t or "最终方案" in t or "可照着执行" in t:
        keys = _intent_keywords(task)
        if not keys:
            instr = task.get("instructions") or ""
            for kw in ["科技馆", "小吃", "建筑", "书店", "展览", "Livehouse", "民族", "花卉", "高铁", "博物馆", "公园"]:
                if kw in instr:
                    keys.append(kw)
        passed = any(k in plan for k in keys) if keys else len(plan) > 400
        detail = f"intent_keys={keys}, matched={[k for k in keys if k in plan]}"
    else:
        passed = len(plan) > 200
        detail = "fallback: non-empty plan"

    return {
        "rubric": t,
        "pass": bool(passed),
        "detail": detail,
        "auto": True,
    }


def score_task_rubrics(task: dict, snap: SessionSnapshot, metrics: dict) -> dict:
    rubrics = _all_rubrics(task)
    rows = [_score_one_rubric(r, task, snap, metrics) for r in rubrics]
    met = sum(1 for r in rows if r["pass"])
    total = len(rows) or 1
    reward = round(met / total, 4)
    return {
        "rubrics": rows,
        "met": met,
        "total": total,
        "reward": reward,
        "full_success": reward >= 1.0,
    }


def score_process_metrics(snap: SessionSnapshot, events: list[dict], metrics: dict) -> dict:
    tool_progress = [e for e in events if e.get("event") == "tool_progress"]
    after_intake = [e for e in tool_progress if e.get("payload", {}).get("phase") == "B"]
    b_tools_visible = len(after_intake) > 0 or metrics.get("b_tool_progress_ok", False)

    intake_ms = metrics.get("intake_ttft_ms")
    intake_ok = intake_ms is not None and 0 <= intake_ms <= 10_000

    image_ms = metrics.get("image_e2e_ms")
    image_ok = metrics.get("image_completed", False)

    eval_tokens = metrics.get("eval_total_tokens")
    session_tokens = snap.total_tokens
    total_tokens = eval_tokens if eval_tokens else session_tokens

    return {
        "intake_within_10s": intake_ok,
        "intake_ttft_ms": intake_ms,
        "b_tool_progress_visible": b_tools_visible,
        "b_tool_progress_events": len(after_intake),
        "image_e2e_ms": image_ms,
        "image_e2e_ok": image_ok,
        "total_tokens": total_tokens,
        "tokens_from_provider": metrics.get("tokens_from_provider", False),
        "turn_complete_count": metrics.get("turn_complete_count", 0),
        "plan_turn_count": metrics.get("plan_turn_count", 0),
        "tool_calls_total": snap.tool_counts["total"],
        "user_turns": snap.user_turns,
        "trajectory_efficiency": {
            "tokens_per_success": snap.total_tokens,
            "tools_per_turn": round(snap.tool_counts["total"] / max(1, snap.user_turns), 2),
            "assistant_messages": len(snap.assistant_messages),
        },
        "multi_turn_robustness": {
            "user_turns": snap.user_turns,
            "has_follow_up_plan": len(snap.final_plan_text) > 300,
        },
    }
