#!/usr/bin/env python3
"""
固定 rubric 评测：根据用户话推断上下文，再对照规则与工具框架。

case 只需 case_id + user_text；适用哪些规则由 rubric_context 自动推断。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from intake_simulator import has_intake_pattern
from rubric_context import find_unconfirmed_party_in_reply, infer_context
from score_dimensions import compute_dimension_scores
from process_metrics import aggregate_process_report, compute_process_metrics
from task_metrics import compute_task_success, summarize_by_difficulty

_BENCH = Path(__file__).resolve().parent


def load_rubric(path: Path | None = None) -> dict:
    p = path or _BENCH / "rubric.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _norm_tools(tools: list) -> set[str]:
    out: set[str] = set()
    for t in tools:
        s = str(t)
        out.add(s)
        out.add(s.replace("lifecare__", "lifecare_"))
    return out


def _tool_names_for_role(rubric: dict, role: str) -> list[str]:
    return list(rubric.get("tool_aliases", {}).get(role, [role]))


def _has_tool(called: set[str], names: list[str]) -> bool:
    for n in names:
        if n in called:
            return True
        short = n.replace("lifecare__", "").replace("lifecare_", "")
        if any(short in c.replace("lifecare__", "") for c in called):
            return True
    return False


def _tools_framework_report(
    rubric: dict, framework_key: str, tools_in_order: list
) -> dict[str, Any]:
    fw = rubric.get("frameworks", {}).get(framework_key, {})
    expected_keys = fw.get("tools") or []
    called = _norm_tools(tools_in_order)
    hit: list[str] = []
    miss: list[str] = []
    for k in expected_keys:
        if _has_tool(called, _tool_names_for_role(rubric, k)):
            hit.append(k)
        else:
            miss.append(k)
    return {
        "framework": framework_key,
        "framework_desc": fw.get("desc"),
        "expected_tool_roles": expected_keys,
        "tools_recorded": list(tools_in_order),
        "roles_hit": hit,
        "roles_miss": miss,
        "pass": len(miss) == 0,
    }


def _early_tool_is_search_or_route(tool_name: str) -> bool:
    s = str(tool_name).lower()
    return "search_places" in s or "plan_route" in s


def _check_rule(rule: dict, rubric: dict, ctx, pred: dict) -> dict:
    check = rule.get("check")
    rid = rule["id"]
    tools = list(pred.get("tools_in_order") or [])
    first_asst = str(pred.get("first_assistant_text") or "")
    if not first_asst and pred.get("turns"):
        first_asst = str((pred["turns"][0] or {}).get("assistant_text") or "")
    final_asst = str(pred.get("assistant_text") or "")

    ok = True
    detail = "ok"
    tools_vs_framework = None

    if check == "first_turn_has_intake":
        ok = has_intake_pattern(first_asst)
        if not ok:
            detail = "first_turn_missing_abc_choices"

    elif check == "forbidden_tools_early":
        early = tools[:2]
        bad = [t for t in early if _early_tool_is_search_or_route(t)]
        ok = len(bad) == 0
        if not ok:
            detail = f"early_forbidden_tools:{bad}"

    elif check == "reply_no_unconfirmed_party_size":
        hits = find_unconfirmed_party_in_reply(final_asst)
        ok = len(hits) == 0
        if not ok:
            detail = f"preset_party_in_reply:{hits}"

    elif check == "tools_framework":
        fw = rule.get("framework")
        tools_vs_framework = _tools_framework_report(rubric, fw, tools)
        ok = tools_vs_framework["pass"]
        if not ok:
            detail = f"miss_roles:{tools_vs_framework['roles_miss']}"

    elif check == "first_turn_sla":
        max_ms = int((rule.get("args") or {}).get("max_ms", 10000))
        turns = pred.get("turns") or []
        ttft = None
        if turns:
            t0 = turns[0]
            ttft = t0.get("time_to_first_assistant_text_ms") or t0.get("time_to_first_progress_ms")
        if ttft is None:
            return {
                "rule_id": rid,
                "desc": rule.get("desc"),
                "applied": True,
                "pass": True,
                "detail": "skipped_no_timing_data",
                "skipped": True,
            }
        ok = float(ttft) <= max_ms
        if not ok:
            detail = f"first_turn_ms:{ttft}>{max_ms}"
        else:
            detail = f"first_turn_ms:{ttft}"

    out: dict[str, Any] = {
        "rule_id": rid,
        "desc": rule.get("desc"),
        "applied": True,
        "pass": ok,
        "detail": detail,
    }
    if tools_vs_framework:
        out["tools_vs_framework"] = tools_vs_framework
    return out


def evaluate_case(case: dict, pred: dict, rubric: dict | None = None) -> dict:
    rubric = rubric or load_rubric()
    users = list(pred.get("user_messages") or [case.get("user_text", "")])
    ctx = infer_context(users)

    applied: list[dict] = []
    skipped_rules: list[str] = []
    for rule in rubric.get("rules") or []:
        when = rule.get("when")
        if when and not ctx.get(when):
            skipped_rules.append(rule["id"])
            continue
        applied.append(_check_rule(rule, rubric, ctx, pred))

    fails = [r for r in applied if not r.get("pass") and not r.get("skipped")]
    tools_fw = [r["tools_vs_framework"] for r in applied if r.get("tools_vs_framework")]

    scoring = compute_dimension_scores(case, pred, ctx, applied, tools_fw)
    rule_pass = len(fails) == 0
    total_score = scoring["total_score"]
    pass_by_score = bool(scoring.get("pass_by_score"))

    task_m = compute_task_success(
        case,
        pred,
        ctx,
        total_score=total_score,
        dimension_scores=scoring.get("dimension_scores"),
        rules_applied=applied,
        pass_threshold=int(scoring.get("pass_threshold", 60)),
    )

    proc_m = compute_process_metrics(
        case,
        pred,
        ctx,
        task_success=task_m.get("task_success"),
        tool_budget=task_m.get("tool_budget"),
        task_row={
            "task_success": task_m.get("task_success"),
            "pass": pass_by_score,
            "reasons_fail": task_m.get("reasons_fail"),
            "task_success_reasons_fail": task_m.get("reasons_fail"),
        },
    )

    return {
        "case_id": case.get("case_id"),
        "difficulty": case.get("difficulty"),
        "pass": pass_by_score,
        "task_success": task_m.get("task_success"),
        "task_success_scope": task_m.get("task_success_scope"),
        "task_metrics": task_m,
        "process_metrics": proc_m,
        "rule_pass": rule_pass,
        "score": total_score,
        "total_score": total_score,
        "dimension_scores": scoring.get("dimension_scores"),
        "pass_threshold": scoring.get("pass_threshold"),
        "pass_by_score": scoring.get("pass_by_score"),
        "context": ctx.flags,
        "context_notes": ctx.notes,
        "rules_applied": applied,
        "rules_skipped": skipped_rules,
        "failures": [f"{r['rule_id']}:{r['detail']}" for r in fails],
        "tools_vs_framework": tools_fw,
        "failure_hints": pred.get("failure_hints") or [],
    }


def _lookup_pred(pred_map: dict, case_id) -> dict | None:
    return pred_map.get(case_id) or pred_map.get(str(case_id))


def evaluate_all(cases: list[dict], pred_map: dict, rubric: dict | None = None) -> dict:
    rubric = rubric or load_rubric()
    results = []
    for case in cases:
        cid = case["case_id"]
        pred = _lookup_pred(pred_map, cid)
        if pred is None:
            results.append(
                {
                    "case_id": cid,
                    "difficulty": case.get("difficulty"),
                    "pass": False,
                    "task_success": False,
                    "score": 0,
                    "failures": ["missing_pred"],
                }
            )
            continue
        results.append(evaluate_case(case, pred, rubric))

    passed = sum(1 for r in results if r.get("pass"))
    task_ok = sum(1 for r in results if r.get("task_success"))
    planning = [r for r in results if (r.get("task_metrics") or {}).get("planning_case")]
    task_ok_plan = sum(1 for r in planning if r.get("task_success"))
    return {
        "rubric_version": rubric.get("version"),
        "cases": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "task_success_count": task_ok,
        "task_success_rate_pct": round(100.0 * task_ok / len(results), 1) if results else 0,
        "planning_cases": len(planning),
        "planning_task_success_count": task_ok_plan,
        "planning_task_success_rate_pct": (
            round(100.0 * task_ok_plan / len(planning), 1) if planning else 0
        ),
        "by_difficulty": summarize_by_difficulty(results, cases).get("by_difficulty"),
        "process_metrics_summary": aggregate_process_report(cases, results),
        "results": results,
    }
