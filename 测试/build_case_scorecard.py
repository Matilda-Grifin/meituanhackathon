#!/usr/bin/env python3
"""从 agent_pred_live.jsonl + agent_eval 生成每条 case 得分卡。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

_BENCH = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", type=Path, default=_BENCH / "results" / "agent_pred_live.jsonl")
    ap.add_argument("--eval", type=Path, default=_BENCH / "results" / "agent_eval_for_evaluator.json")
    ap.add_argument("-o", type=Path, default=_BENCH / "results" / "case_scorecard.json")
    args = ap.parse_args()

    preds = [json.loads(l) for l in args.pred.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.eval.is_file():
        eval_r = json.loads(args.eval.read_text(encoding="utf-8"))
    else:
        eval_r = {"results": []}
    emap = {r["case_id"]: r for r in eval_r.get("results") or []}

    cases = []
    for p in preds:
        cid = p["case_id"]
        ev = emap.get(cid, {})
        tools_fw = ev.get("tools_vs_framework") or []
        turns = p.get("turns") or []
        per_turn = []
        for t in turns:
            per_turn.append(
                {
                    "assistant_turn": t.get("assistant_turn"),
                    "duration_ms": t.get("duration_ms"),
                    "time_to_first_assistant_text_ms": t.get("time_to_first_assistant_text_ms"),
                    "time_to_first_progress_ms": t.get("time_to_first_progress_ms"),
                    "tools": t.get("tools") or [],
                    "user_message_preview": (t.get("user_message") or "")[:80],
                }
            )
        t0 = turns[0] if turns else {}
        first_ttft = t0.get("time_to_first_assistant_text_ms") or t0.get("time_to_first_progress_ms")
        tm = ev.get("task_metrics") or {}
        pm = ev.get("process_metrics") or {}
        budget = tm.get("tool_budget") or {}
        intake = tm.get("intake_metrics") or {}
        cases.append(
            {
                "case_id": cid,
                "difficulty": ev.get("difficulty"),
                "pass": bool(ev.get("pass")),
                "task_success": ev.get("task_success"),
                "task_success_scope": ev.get("task_success_scope"),
                "total_score": ev.get("total_score", ev.get("score", 0)),
                "rule_pass": ev.get("rule_pass"),
                "dimension_scores": ev.get("dimension_scores") or [],
                "failures": ev.get("failures") or [],
                "task_fail_reasons": tm.get("reasons_fail") or [],
                "context": ev.get("context") or {},
                "rules_applied": [r.get("rule_id") for r in (ev.get("rules_applied") or [])],
                "tools_vs_framework": tools_fw,
                "tool_budget": budget,
                "plan_structure_score": pm.get("plan_structure_score"),
                "trajectory_efficiency_score": pm.get("trajectory_efficiency_score"),
                "tool_expect_pass": pm.get("tool_expect_pass"),
                "tool_precision_pct": pm.get("tool_precision_pct"),
                "tool_recall_pct": pm.get("tool_recall_pct"),
                "retry_exceeded": pm.get("retry_exceeded"),
                "schema_compliance_rate": (pm.get("tool_schema") or {}).get("schema_compliance_rate"),
                "evidence_grounding_pct": pm.get("evidence_grounding_pct"),
                "failure_mode": pm.get("failure_mode"),
                "intake_within_10s": intake.get("intake_within_10s"),
                "tool_progress_visible": intake.get("tool_progress_visible"),
                "stream_after_tools_ok": intake.get("stream_after_tools_ok"),
                "turn_count": len(turns),
                "simulation_steps": len(p.get("simulation_log") or []),
                "user_message_count": len(p.get("user_messages") or []),
                "latency_total_ms": p.get("latency_first_token_ms"),
                "first_turn_duration_ms": t0.get("duration_ms") if turns else None,
                "first_token_ms": first_ttft,
                "tools_in_order": p.get("tools_in_order") or [],
                "failure_hints": p.get("failure_hints") or [],
                "turns_detail": per_turn,
                "session_id": p.get("session_id"),
            }
        )

    passed = sum(1 for c in cases if c["pass"])
    task_ok = sum(1 for c in cases if c.get("task_success"))
    avg_score = int(round(sum(c["total_score"] for c in cases) / len(cases))) if cases else 0
    out = {
        "summary": {
            "passed": passed,
            "total": len(cases),
            "pass_rate": round(passed / len(cases) * 100, 1) if cases else 0,
            "task_success_count": task_ok,
            "task_success_rate": round(task_ok / len(cases) * 100, 1) if cases else 0,
            "avg_total_score": avg_score,
            "pass_threshold": 60,
            "note": "pass=total_score>=60；task_success=指标.md 北极星（规划类含工具预算等）",
        },
        "cases": cases,
    }
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.o), "passed": passed, "total": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
