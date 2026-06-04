#!/usr/bin/env python3
"""多轮脚本裁判指标（对齐 HTML 第二节量化分数，无需 LLM Judge）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_TIME_BLOCK = re.compile(r"\d{1,2}[:：]\d{2}|\d{1,2}\s*点")
_INDOOR_KW = re.compile(r"室内|博物馆|商场|展览|美术馆|书店|亲子", re.I)
_NO_SPICY_KW = re.compile(r"不辣|免辣|清淡|忌口", re.I)
_TRANSPORT_KW = re.compile(r"地铁|公交|打车|分钟|公里|驾车|步行", re.I)
_BACKUP_KW = re.compile(r"备选|方案[一二2]|Plan B|如果.*则", re.I)
_QUESTION = re.compile(r"[？?]|请问|能否告知|告诉我")


def _all_assistant_text(pred: dict) -> str:
    parts = [pred.get("assistant_text") or ""]
    for t in pred.get("turns") or []:
        parts.append(t.get("assistant_text") or "")
    return "\n".join(parts)


def _match_constraint(text: str, spec: dict) -> bool:
    key = spec.get("key")
    val = spec.get("value")
    match = spec.get("match", "keyword_in_output")
    if match == "lte_in_output" and key == "budget_max":
        nums = [int(x) for x in re.findall(r"(\d{2,4})\s*元", text)]
        return any(n <= int(val) for n in nums) if nums else False
    if match == "number_in_output":
        return str(val) in text
    if match == "keyword_in_output":
        if key == "venue_type" and val == "indoor":
            return bool(_INDOOR_KW.search(text))
        if key == "diet" and val == "no_spicy":
            return bool(_NO_SPICY_KW.search(text))
        if key == "transport":
            return bool(_TRANSPORT_KW.search(text))
        if key == "city":
            return str(val) in text
    if match == "time_blocks_in_output":
        return len(_TIME_BLOCK.findall(text)) >= 2
    if match == "backup_plan_in_output":
        return bool(_BACKUP_KW.search(text))
    return str(val) in text if val is not None else False


def score_history_constraints(judge: dict, pred: dict) -> dict[str, Any]:
    required = (judge.get("expected_behavior") or {}).get("history_constraints_required") or []
    if not required:
        return {"hit": 0, "total": 0, "rate": 1.0, "details": []}
    text = _all_assistant_text(pred)
    details = []
    hit = 0
    for spec in required:
        ok = _match_constraint(text, spec)
        if ok:
            hit += 1
        details.append({"spec": spec, "hit": ok})
    total = len(required)
    return {"hit": hit, "total": total, "rate": hit / total if total else 1.0, "details": details}


def score_followup_efficiency(judge: dict, pred: dict) -> dict[str, Any]:
    policy = (judge.get("expected_behavior") or {}).get("followup_policy") or {}
    scripted = int(policy.get("scripted_followups") or 0)
    turns = pred.get("turns") or []
    if scripted <= 0 or len(turns) <= 1:
        return {"correct": 1, "total": 1, "rate": 1.0, "note": "no_scripted_followups"}

    correct = 0
    total = 0
    seen_questions: set[str] = set()
    for i, turn in enumerate(turns[:-1], start=1):
        asst = turn.get("assistant_text") or ""
        if i > scripted:
            break
        total += 1
        is_question = bool(_QUESTION.search(asst))
        q_norm = re.sub(r"\s+", "", asst[:120])
        repeated = q_norm in seen_questions and q_norm
        if q_norm:
            seen_questions.add(q_norm)
        if policy.get("must_not_repeat_slots") and repeated:
            continue
        if is_question or not repeated:
            correct += 1
    if total == 0:
        total = 1
        correct = 1
    return {"correct": correct, "total": total, "rate": correct / total}


def score_replan(judge: dict, pred: dict) -> dict[str, Any]:
    policy = (judge.get("expected_behavior") or {}).get("replan_policy") or {}
    triggers = policy.get("replan_required_when") or []
    turns = pred.get("turns") or []
    if not triggers or len(turns) < 2:
        return {"required": 0, "success": 0, "rate": 1.0, "note": "no_replan_required"}

    first = turns[0].get("assistant_text") or ""
    last = turns[-1].get("assistant_text") or ""
    changed = first.strip() != last.strip() and len(last) > 80
    constraints = score_history_constraints(judge, pred)
    ok = changed and constraints["rate"] >= 0.5
    return {"required": 1, "success": 1 if ok else 0, "rate": 1.0 if ok else 0.0, "text_changed": changed}


def score_tool_compliance(pred: dict, rubric_result: dict | None) -> dict[str, Any]:
    failures = (rubric_result or {}).get("failures") or []
    traj_fail = [f for f in failures if "tool" in f.lower() or "intake" in f.lower() or "route" in f.lower()]
    checkpoints = max(1, len(pred.get("tools_in_order") or []) + 3)
    violations = len(traj_fail)
    rate = max(0.0, 1.0 - violations / checkpoints)
    return {"violations": violations, "checkpoints": checkpoints, "rate": rate}


def evaluate_multiturn_case(judge: dict, pred: dict, rubric_result: dict | None = None) -> dict[str, Any]:
    hist = score_history_constraints(judge, pred)
    follow = score_followup_efficiency(judge, pred)
    replan = score_replan(judge, pred)
    tools = score_tool_compliance(pred, rubric_result)
    execution_ok = bool((rubric_result or {}).get("task_success"))
    return {
        "case_id": judge.get("case_id"),
        "history_constraint_rate": hist["rate"],
        "followup_efficiency_rate": follow["rate"],
        "replan_success": replan.get("success", 0),
        "replan_required": replan.get("required", 0),
        "tool_compliance_rate": tools["rate"],
        "execution_success": execution_ok,
        "metrics_detail": {
            "history": hist,
            "followup": follow,
            "replan": replan,
            "tools": tools,
        },
    }


def evaluate_multiturn_all(
    judges: list[dict],
    preds: dict[Any, dict],
    rubric_by_case: dict[Any, dict] | None = None,
) -> dict[str, Any]:
    rubric_by_case = rubric_by_case or {}
    rows = []
    for j in judges:
        cid = j["case_id"]
        pred = preds.get(cid) or preds.get(str(cid))
        if not pred:
            rows.append({"case_id": cid, "missing_pred": True})
            continue
        rr = rubric_by_case.get(cid) or rubric_by_case.get(str(cid))
        rows.append(evaluate_multiturn_case(j, pred, rr))

    valid = [r for r in rows if not r.get("missing_pred")]
    n = len(valid) or 1

    def _avg(key: str) -> float:
        vals = [r.get(key, 0) for r in valid if isinstance(r.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else 0.0

    replan_req = sum(r.get("replan_required", 0) for r in valid)
    replan_ok = sum(r.get("replan_success", 0) for r in valid)

    return {
        "cases": len(judges),
        "scored": len(valid),
        "missing_pred": len(rows) - len(valid),
        "history_constraint_rate_avg": round(_avg("history_constraint_rate"), 4),
        "followup_efficiency_rate_avg": round(_avg("followup_efficiency_rate"), 4),
        "replan_success_rate": round(replan_ok / replan_req, 4) if replan_req else 1.0,
        "tool_compliance_rate_avg": round(_avg("tool_compliance_rate"), 4),
        "execution_success_rate": round(
            sum(1 for r in valid if r.get("execution_success")) / n, 4
        ),
        "results": rows,
    }


def load_judges(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))
