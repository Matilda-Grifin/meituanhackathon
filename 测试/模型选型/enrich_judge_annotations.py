#!/usr/bin/env python3
"""从多轮测试集 simulation 脚本生成裁判标注（脚本可读，不进模型 prompt）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[1]
MULTITURN = _BENCH / "eval_cases" / "full" / "多轮测试集.json"
OUT = Path(__file__).resolve().parent / "judge" / "multiturn_judge.json"

_BUDGET = re.compile(r"预算(?:控制)?(?:在)?(\d+)", re.I)
_INDOOR = re.compile(r"室内|下雨", re.I)
_NO_SPICY = re.compile(r"忌口|不能吃辣|不吃辣", re.I)
_SCHEDULE = re.compile(r"时间表|可直接执行|动线|交通方式|预计耗时", re.I)
_BACKUP = re.compile(r"备选方案|主方案", re.I)
_REPLAN = re.compile(r"改|下雨|预算|同行|室内|不可行|重规划|备选", re.I)
_REPEAT = re.compile(r"不要重复|别再问|重复问题", re.I)
_TRANSPORT = re.compile(r"交通方便|地铁|折返", re.I)


def _constraints_from_messages(msgs: list[str], facts: dict) -> list[dict]:
    text = " ".join(msgs)
    out: list[dict] = []
    m = _BUDGET.search(text)
    if m:
        out.append({"key": "budget_max", "value": int(m.group(1)), "match": "lte_in_output"})
    if _INDOOR.search(text):
        out.append({"key": "venue_type", "value": "indoor", "match": "keyword_in_output"})
    if _NO_SPICY.search(text):
        out.append({"key": "diet", "value": "no_spicy", "match": "keyword_in_output"})
    if _TRANSPORT.search(text):
        out.append({"key": "transport", "value": "convenient", "match": "keyword_in_output"})
    if facts.get("child_age"):
        out.append({"key": "child_age", "value": facts["child_age"], "match": "number_in_output"})
    if facts.get("city"):
        out.append({"key": "city", "value": facts["city"], "match": "keyword_in_output"})
    if _SCHEDULE.search(text):
        out.append({"key": "executable_plan", "value": True, "match": "time_blocks_in_output"})
    if _BACKUP.search(text):
        out.append({"key": "backup_plan", "value": True, "match": "backup_plan_in_output"})
    return out


def _build_case(case: dict) -> dict:
    sim = case.get("simulation") or {}
    replies = sim.get("replies") or []
    script_msgs = [r.get("user_message", "") for r in replies if r.get("reply_mode") == "script"]
    facts = case.get("user_facts") or {}
    replan_triggers = []
    for msg in script_msgs:
        if _REPLAN.search(msg):
            replan_triggers.append(msg[:80])

    return {
        "case_id": case["case_id"],
        "source_case_id": case.get("source_case_id"),
        "difficulty": case.get("difficulty"),
        "expected_behavior": {
            "history_constraints_required": _constraints_from_messages(
                [case.get("user_text", "")] + script_msgs, facts
            ),
            "followup_policy": {
                "scripted_followups": len(script_msgs),
                "must_not_repeat_slots": any(_REPEAT.search(m) for m in script_msgs),
                "allow_clarification_before_script": True,
            },
            "replan_policy": {
                "replan_required_when": replan_triggers or (["user_followup"] if script_msgs else []),
                "success_criteria": ["assistant_text_changed", "constraints_still_satisfied"],
            },
            "execution_success_criteria": ["task_success_from_rubric"],
        },
        "must_not": {
            "forbidden_actions": (["repeat_same_intake_question"] if any(_REPEAT.search(m) for m in script_msgs) else []),
        },
        "pass_thresholds": {
            "history_constraint_rate": 0.85,
            "followup_efficiency_rate": 0.80,
            "replan_success_rate": 0.75,
        },
    }


def main() -> None:
    cases = json.loads(MULTITURN.read_text(encoding="utf-8"))
    judges = [_build_case(c) for c in cases]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(judges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(judges)} cases)")


if __name__ == "__main__":
    main()
