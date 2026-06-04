#!/usr/bin/env python3
"""
§6.1–6.4 过程指标：轨迹、工具 Schema、推理效率、鲁棒性汇总。
与 task_metrics 配合；evaluate_case 写入 process_metrics 字段。
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

from tool_schema_validate import validate_pred_tool_calls

_BENCH = Path(__file__).resolve().parent

# 工具名 → 角色（与 task_metrics 一致）
TOOL_ROLE = {
    "lifecare_search_places": "search",
    "lifecare_get_weather": "weather",
    "lifecare_plan_route": "route",
}

ROBUSTNESS_CASE_IDS = {20, 21, 22, 23, 25, 26}
PLANNING_CASE_TYPES = {"planning", "intake_then_plan", "special"}

# 预算 SLA（§6.3，可按答辩调整）
BUDGET_SLA = {
    "tools_per_task_p95_max": 12,
    "latency_p95_max_s": 120.0,
    "token_p95_max": 80000,
}


def _tools_in_order(pred: dict) -> list[str]:
    out: list[str] = []
    for t in pred.get("turns") or []:
        for name in t.get("tools") or []:
            out.append(str(name))
    if not out and pred.get("tools"):
        out = [str(x) for x in pred["tools"]]
    return out


def _tool_roles_in_order(pred: dict) -> list[str]:
    roles: list[str] = []
    for name in _tools_in_order(pred):
        key = name.replace("lifecare__", "").replace("lifecare_", "")
        for full, role in TOOL_ROLE.items():
            if full in name or key in full:
                roles.append(role)
                break
    return roles


def resolve_tool_expect(case: dict, ctx: dict) -> dict[str, Any]:
    """从 case.eval.tool_expect 解析 required/forbidden 角色。"""
    ev = (case.get("eval") or {})
    te = ev.get("tool_expect") or {}
    required = list(te.get("required_roles") or te.get("required") or [])
    forbidden = list(te.get("forbidden_roles") or te.get("forbidden") or [])
    if not required and not forbidden:
        # 规划类默认：至少 search + weather
        if case.get("type") in PLANNING_CASE_TYPES or case.get("difficulty") in ("easy", "medium", "hard"):
            if case.get("case_id") not in (20, 21):
                required = ["search", "weather"]
    return {"required_roles": required, "forbidden_roles": forbidden, "raw": te}


def compute_tool_role_pr(
    case: dict, pred: dict, ctx: dict
) -> dict[str, Any]:
    expect = resolve_tool_expect(case, ctx)
    roles = set(_tool_roles_in_order(pred))
    req = set(expect["required_roles"])
    forb = set(expect["forbidden_roles"])

    hit = len(req & roles)
    precision = round(100.0 * hit / len(roles), 1) if roles else (100.0 if not req else 0.0)
    recall = round(100.0 * hit / len(req), 1) if req else None
    forbidden_hit = list(forb & roles)
    tool_expect_pass = (not req or req <= roles) and not forbidden_hit

    return {
        "tool_expect_pass": tool_expect_pass,
        "tool_precision_pct": precision,
        "tool_recall_pct": recall,
        "required_roles": list(req),
        "forbidden_roles": list(forb),
        "roles_observed": sorted(roles),
        "forbidden_hit": forbidden_hit,
    }


def detect_retry_exceeded(tools: list[str], max_consecutive: int = 2) -> dict[str, Any]:
    """相邻同工具调用 > max_consecutive 视为重试超限。"""
    if not tools:
        return {"retry_exceeded": False, "max_consecutive_same": 0, "offending_tool": None}
    best = 1
    cur = 1
    offender = tools[0]
    best_tool = offender
    for i in range(1, len(tools)):
        if tools[i] == tools[i - 1]:
            cur += 1
            if cur > best:
                best = cur
                best_tool = tools[i]
        else:
            cur = 1
    exceeded = best > max_consecutive
    return {
        "retry_exceeded": exceeded,
        "max_consecutive_same": best,
        "offending_tool": best_tool if exceeded else None,
    }


def compute_plan_structure_score(case: dict, pred: dict) -> dict[str, Any]:
    """
    规划结构分（0–100）：日程块、交通/住宿提及、天数与 case 一致等启发式。
    """
    text = " ".join(
        str(t.get("assistant") or t.get("content") or "")
        for t in (pred.get("turns") or [])
    ).lower()
    if not text and pred.get("final_answer"):
        text = str(pred["final_answer"]).lower()

    score = 40
    reasons: list[str] = []
    if re.search(r"(第[一二三四五六七八九十\d]+天|day\s*\d|d\d)", text):
        score += 20
        reasons.append("has_day_markers")
    if re.search(r"(上午|下午|晚上|morning|afternoon)", text):
        score += 15
        reasons.append("has_time_slots")
    if re.search(r"(交通|地铁|打车|路线|route|驾车)", text):
        score += 10
        reasons.append("mentions_transport")
    if re.search(r"(酒店|住宿|民宿|住)", text):
        score += 10
        reasons.append("mentions_lodging")
    dur = str((case.get("user_context") or {}).get("duration") or "")
    if dur and dur[:1] in text or "5天" in text or "五天" in text:
        score += 5
        reasons.append("duration_aligned")

    return {
        "plan_structure_score": min(100, score),
        "plan_structure_signals": reasons,
    }


def compute_trajectory_efficiency(
    case: dict,
    pred: dict,
    *,
    task_success: bool,
    tool_budget: dict | None,
) -> dict[str, Any]:
    """轨迹效率：成功前提下工具数/预算比 + 轮次惩罚。"""
    tools = _tools_in_order(pred)
    n_tools = len(tools)
    n_turns = len(pred.get("turns") or [])
    budget = tool_budget or {}
    max_route = budget.get("max_plan_route")
    max_total = budget.get("max_tools_total")

    ratio_route = None
    if max_route and max_route > 0:
        route_n = sum(1 for t in tools if "plan_route" in t)
        ratio_route = round(route_n / max_route, 2)

    eff = 50.0
    if task_success:
        eff += 30.0
    if max_total and n_tools <= max_total:
        eff += 10.0
    elif max_total:
        eff -= min(30.0, 5.0 * (n_tools - max_total))
    if n_turns > 0 and n_tools / max(n_turns, 1) <= 2:
        eff += 10.0

    return {
        "trajectory_efficiency_score": round(max(0.0, min(100.0, eff)), 1),
        "tool_count": n_tools,
        "turn_count": n_turns,
        "route_to_budget_ratio": ratio_route,
    }


def compute_evidence_grounding(pred: dict, ctx: dict) -> dict[str, Any]:
    """规则版证据接地：回复含 POI/天气/路线类关键词或引用工具结果痕迹。"""
    text = " ".join(
        str(t.get("assistant") or "")
        for t in (pred.get("turns") or [])
    )
    if pred.get("final_answer"):
        text += " " + str(pred["final_answer"])

    tools = _tools_in_order(pred)
    signals = []
    if any("search_places" in t for t in tools):
        if re.search(r"(店|馆|景区|poi|评分|人均)", text, re.I):
            signals.append("poi_mention")
    if any("get_weather" in t for t in tools):
        if re.search(r"(℃|度|晴|雨|阴|weather|气温)", text, re.I):
            signals.append("weather_mention")
    if any("plan_route" in t for t in tools):
        if re.search(r"(公里|分钟|驾车|路线|km)", text, re.I):
            signals.append("route_mention")

    n_expected = sum(
        1
        for t in tools
        if any(k in t for k in ("search_places", "get_weather", "plan_route"))
    )
    rate = round(100.0 * len(signals) / max(n_expected, 1), 1) if n_expected else None
    return {
        "evidence_grounding_pct": rate,
        "evidence_signals": signals,
        "tools_used": len(tools),
    }


def compute_stage_latency(pred: dict) -> dict[str, Any]:
    """首响三阶段耗时（秒），来自 pred.stage_timings 或 turns。"""
    st = pred.get("stage_timings") or {}
    return {
        "intake_first_visible_s": st.get("intake_first_visible_s"),
        "tool_progress_visible_s": st.get("tool_progress_visible_s"),
        "post_tool_long_reply_s": st.get("post_tool_long_reply_s"),
        "total_elapsed_s": st.get("total_elapsed_s") or pred.get("elapsed_s"),
    }


def compute_token_usage(pred: dict) -> dict[str, Any]:
    u = pred.get("token_usage") or {}
    if not u:
        total = 0
        for turn in pred.get("turns") or []:
            meta = turn.get("meta") or {}
            tu = meta.get("usage") or meta.get("tokenUsage") or {}
            total += int(tu.get("total_tokens") or tu.get("total") or 0)
        if total:
            u = {"total_tokens": total}
    return {
        "prompt_tokens": u.get("prompt_tokens"),
        "completion_tokens": u.get("completion_tokens"),
        "total_tokens": u.get("total_tokens"),
    }


def classify_failure_mode(row: dict) -> str:
    """plan | tool | environment"""
    reasons = row.get("task_success_reasons_fail") or row.get("reasons_fail") or []
    text = " ".join(str(r) for r in reasons).lower()
    if any(
        k in text
        for k in (
            "schema",
            "retry",
            "tool_expect",
            "forbidden_tools",
            "budget",
            "max_plan_route",
            "max_tools",
            "降级",
            "degrad",
        )
    ):
        return "tool"
    if any(k in text for k in ("拒答", "illegal", "conflict", "冲突", "replan", "重规划")):
        return "environment"
    if any(k in text for k in ("plan_completeness", "pass", "score", "structure")):
        return "plan"
    if not row.get("task_success") and row.get("pass"):
        return "plan"
    if not row.get("task_success"):
        return "plan"
    return "plan"


def compute_robustness_extras(case: dict, pred: dict, ctx: dict) -> dict[str, Any]:
    """case 25/26：改城市、改偏好。"""
    ev = case.get("eval") or {}
    text = " ".join(
        str(t.get("assistant") or "")
        for t in (pred.get("turns") or [])
    )
    if pred.get("final_answer"):
        text += " " + str(pred["final_answer"])

    out: dict[str, Any] = {}
    if ev.get("expect_replan_city_change"):
        new_city = (case.get("user_context") or {}).get("city_change_to") or ev.get("city_change_to")
        ok = bool(new_city and str(new_city) in text)
        out["replan_city_change_ok"] = ok
        out["expected_city"] = new_city
    if ev.get("expect_preference_shift"):
        kw = ev.get("preference_keywords") or ["素食", "不吃辣", "清淡"]
        out["preference_shift_ack"] = any(k in text for k in kw)
    return out


def compute_process_metrics(
    case: dict,
    pred: dict,
    ctx: dict,
    *,
    task_success: bool | None = None,
    tool_budget: dict | None = None,
    task_row: dict | None = None,
) -> dict[str, Any]:
    """单 case 过程指标包。"""
    tool_pr = compute_tool_role_pr(case, pred, ctx)
    retry = detect_retry_exceeded(_tools_in_order(pred))
    schema = validate_pred_tool_calls(pred)
    plan_struct = compute_plan_structure_score(case, pred)
    traj = compute_trajectory_efficiency(
        case, pred, task_success=bool(task_success), tool_budget=tool_budget
    )
    evidence = compute_evidence_grounding(pred, ctx)
    latency = compute_stage_latency(pred)
    tokens = compute_token_usage(pred)
    robust = compute_robustness_extras(case, pred, ctx)

    tool_expect_pass = tool_pr["tool_expect_pass"] and not retry["retry_exceeded"]
    if schema.get("schema_compliance_rate") is not None and schema["schema_compliance_rate"] < 100:
        tool_expect_pass = False

    out = {
        **tool_pr,
        **retry,
        "tool_schema": schema,
        **plan_struct,
        **traj,
        **evidence,
        **latency,
        **tokens,
        **robust,
        "tool_expect_pass_strict": tool_expect_pass,
    }
    if task_row:
        out["failure_mode"] = classify_failure_mode(task_row)
    return out


def _percentile(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return round(s[f], 2)
    return round(s[f] + (s[c] - s[f]) * (k - f), 2)


def aggregate_process_report(
    cases: list[dict],
    results: list[dict],
) -> dict[str, Any]:
    """全库 P50/P95、失败归因、鲁棒 task_success 率、budget SLA。"""
    by_id = {int(c.get("case_id") or c.get("id") or 0): c for c in cases}
    tool_counts: list[int] = []
    latencies: list[float] = []
    tokens: list[int] = []
    precisions: list[float] = []
    recalls: list[float] = []
    failure_modes: dict[str, int] = {"plan": 0, "tool": 0, "environment": 0}

    robust_ok = 0
    robust_n = 0
    schema_rates: list[float] = []

    for r in results:
        cid = int(r.get("case_id") or 0)
        pm = r.get("process_metrics") or {}
        if pm.get("failure_mode"):
            failure_modes[pm["failure_mode"]] = failure_modes.get(pm["failure_mode"], 0) + 1
        elif not r.get("task_success"):
            fm = classify_failure_mode(r)
            failure_modes[fm] = failure_modes.get(fm, 0) + 1

        if r.get("task_success"):
            tc = pm.get("tool_count")
            if tc is not None:
                tool_counts.append(int(tc))
            el = pm.get("total_elapsed_s") or r.get("elapsed_s")
            if el is not None:
                latencies.append(float(el))
            tt = pm.get("total_tokens")
            if tt:
                tokens.append(int(tt))

        if pm.get("tool_precision_pct") is not None:
            precisions.append(float(pm["tool_precision_pct"]))
        if pm.get("tool_recall_pct") is not None:
            recalls.append(float(pm["tool_recall_pct"]))
        sr = (pm.get("tool_schema") or {}).get("schema_compliance_rate")
        if sr is not None:
            schema_rates.append(float(sr))

        if cid in ROBUSTNESS_CASE_IDS:
            robust_n += 1
            if r.get("task_success"):
                robust_ok += 1

    sla_tools = _percentile([float(x) for x in tool_counts], 95)
    sla_lat = _percentile(latencies, 95)
    sla_tok = _percentile([float(x) for x in tokens], 95)
    budget_sla_pass = True
    if sla_tools is not None and sla_tools > BUDGET_SLA["tools_per_task_p95_max"]:
        budget_sla_pass = False
    if sla_lat is not None and sla_lat > BUDGET_SLA["latency_p95_max_s"]:
        budget_sla_pass = False
    if sla_tok is not None and sla_tok > BUDGET_SLA["token_p95_max"]:
        budget_sla_pass = False

    return {
        "failure_mode_distribution": failure_modes,
        "tools_per_task_p50": _percentile([float(x) for x in tool_counts], 50),
        "tools_per_task_p95": sla_tools,
        "latency_p50_s": _percentile(latencies, 50),
        "latency_p95_s": sla_lat,
        "token_p50": _percentile([float(x) for x in tokens], 50),
        "token_p95": sla_tok,
        "tool_precision_avg": round(statistics.mean(precisions), 1) if precisions else None,
        "tool_recall_avg": round(statistics.mean(recalls), 1) if recalls else None,
        "schema_compliance_avg": round(statistics.mean(schema_rates), 1) if schema_rates else None,
        "robustness_task_success_rate": round(100.0 * robust_ok / robust_n, 1) if robust_n else None,
        "robustness_cases": sorted(ROBUSTNESS_CASE_IDS),
        "robustness_ok": robust_ok,
        "robustness_n": robust_n,
        "budget_sla": BUDGET_SLA,
        "budget_sla_pass": budget_sla_pass,
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="从 agent_eval JSON 生成 process_metrics 报告")
    ap.add_argument("--eval-json", type=Path, required=True)
    ap.add_argument("--cases", type=Path, default=_BENCH / "eval_cases/dev/cases.json")
    ap.add_argument("-o", "--output", type=Path, default=_BENCH / "results/process_metrics_report.json")
    args = ap.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    data = json.loads(args.eval_json.read_text(encoding="utf-8"))
    results = data if isinstance(data, list) else data.get("results") or data.get("cases") or []
    report = aggregate_process_report(cases, results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
