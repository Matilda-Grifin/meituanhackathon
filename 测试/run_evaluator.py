#!/usr/bin/env python3
"""
测评后 Evaluator：规则分 + 模拟答题一致性 + 失败归因（可选 DeepEval）。

业界常见分层（AgentBench / DeepEval / LangSmith）：
  1) 确定性断言（本仓库 run_agent_eval）
  2) 工具框架（run_agent_eval 内 rubric）
  3) LLM-as-Judge 抽检（run_deepeval_judge，可选）

用法：
  python benchmark/run_evaluator.py --pred benchmark/results/agent_pred_live.jsonl
  python benchmark/run_evaluator.py --pred ... --audit benchmark/results/simulation_audit.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BENCH = Path(__file__).resolve().parent
_PY = sys.executable

FAILURE_CAUSES: dict[str, str] = {
    "should_ask_intake": "未按 travel-intake 出选择题（A 阶段）",
    "should_ask_intake_on_first_turn": "首条回复未出 A/B/C 选择题，直接给计划或闲聊",
    "forbidden_tools_before_intake": "槽位未齐就调了 search/route",
    "required_tools_miss": "槽位已齐但未调必需 MCP 工具",
    "required_tools_after_simulation_miss": "模拟用户答完题后仍未调 weather/search",
    "must_not_contain_assistant": "回复出现禁止话术（如未确认的 4 人）",
    "must_contain_categories_hint": "方案缺少餐饮/景点等类别信息",
    "missing_pred": "未采集到该 case 的 pred",
    "total_score<60": "六维加权总分未达及格线",
    "plan_completeness<70": "规划类方案完整度不足（吃+玩等）",
    "plan_route_count>": "算路工具次数超过动态上限 max_plan_route(D,A)",
    "tools_total>": "总工具调用超过 M(D)",
    "forbidden_tools_before_intake": "槽位未齐时首轮调了 search/route",
    "refusal_expected": "非法/有害请求未正确拒答",
    "tool_degrade_ack_missing": "工具不可用但未向用户说明",
    "schedule_conflict_not_acknowledged": "行程时间冲突未指出",
    "replan_indoor_missing": "要求改室内后方案仍偏户外",
    "budget_breakdown_missing": "未给出预算/分天费用结构",
    "replan_city_change_missing": "改城市后方案未体现新目的地",
    "preference_shift_not_acknowledged": "偏好变更后方案未体现新约束",
    "retry_exceeded": "相邻同工具连续重试超过上限",
    "weather_tool_missing": "查天气场景未调用 get_weather",
    "simulation_mismatch": "模拟用户答案与 case 脚本不一致",
    "simulation_missing": "应有模拟答题但未记录 audit",
}


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _check_simulation_consistency(cases: list[dict], audit_rows: list[dict]) -> list[dict]:
    """对照 gold.scripted choices 与 audit 里实际发送的 user_reply。"""
    audit_by_case: dict[str, list[dict]] = {}
    for a in audit_rows:
        audit_by_case.setdefault(a["case_id"], []).append(a)

    checks: list[dict] = []
    for case in cases:
        cid = case["case_id"]
        sim = case.get("simulation") or {}
        if not sim.get("replies") and not case.get("followup_user"):
            continue
        audits = audit_by_case.get(cid) or []
        if (sim.get("replies") or case.get("followup_user")) and not audits:
            checks.append({"case_id": cid, "pass": False, "reason": "simulation_missing"})
            continue
        for i, spec in enumerate(sim.get("replies") or []):
            spec = {
                **spec,
                "user_facts": {**(case.get("user_facts") or {}), **(spec.get("user_facts") or {})},
            }
            if i >= len(audits):
                checks.append({"case_id": cid, "pass": False, "reason": f"simulation_missing_turn_{i+1}"})
                break
            aud = audits[i]
            sent = aud.get("user_reply_sent") or ""
            if aud.get("reply_source") in ("llm", "script_fallback") or spec.get("reply_mode") == "llm":
                # 口语模式只检查有回复
                ok = bool(sent.strip())
                checks.append(
                    {
                        "case_id": cid,
                        "turn": i + 1,
                        "pass": ok,
                        "reason": None if ok else "simulation_empty",
                        "reply_source": aud.get("reply_source"),
                        "sent": sent[:200],
                    }
                )
                continue
            expected = spec.get("choices") or aud.get("resolved_choices") or {}
            if expected:
                ok = True
                for q, letter in expected.items():
                    qn = str(q).lstrip("q")
                    if f"第{qn}题选{letter.upper()}" not in sent and f"第{qn}题选{letter.lower()}" not in sent:
                        ok = False
                note = (spec.get("other_note") or "").strip()
                if note and note not in sent:
                    ok = False
                checks.append(
                    {
                        "case_id": cid,
                        "turn": i + 1,
                        "pass": ok,
                        "reason": None if ok else "simulation_mismatch",
                        "expected_choices": expected,
                        "sent": sent[:200],
                    }
                )
                continue
            facts = spec.get("user_facts") or {}
            ok = True
            if facts.get("use_defaults"):
                ok = "默认" in sent
            elif facts:
                if facts.get("party_size") is not None:
                    ps = str(facts["party_size"])
                    ok = ps in sent or f"{ps}人" in sent or f"{ps}个" in sent
                if ok and facts.get("party_detail"):
                    ok = any(w in sent for w in str(facts["party_detail"]).split() if len(w) >= 2)
                if ok and facts.get("city"):
                    ok = str(facts["city"]) in sent
                for bad in facts.get("must_not_say") or []:
                    if str(bad) in sent:
                        ok = False
            else:
                expected = spec.get("choices") or {}
                for q, letter in expected.items():
                    qn = str(q).lstrip("q")
                    if f"第{qn}题选{letter.upper()}" not in sent and f"第{qn}题选{letter.lower()}" not in sent:
                        ok = False
                note = (spec.get("other_note") or spec.get("q3_other") or "").strip()
                if note and note not in sent:
                    ok = False
            checks.append(
                {
                    "case_id": cid,
                    "turn": i + 1,
                    "pass": ok,
                    "reason": None if ok else "simulation_mismatch",
                    "user_facts": facts or None,
                    "sent": sent[:200],
                    "assistant_excerpt": (aud.get("assistant_prompt_excerpt") or "")[:120],
                }
            )
    return checks


def _diagnose(rule_results: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rule_results:
        if r.get("pass"):
            continue
        causes = []
        for f in r.get("failures") or []:
            key = f.split(":")[0]
            causes.append(
                {
                    "code": key,
                    "detail": f,
                    "human": FAILURE_CAUSES.get(key, "见 detail"),
                }
            )
        for h in r.get("failure_hints") or []:
            causes.append({"code": "hint", "detail": h, "human": h})
        for reason in (r.get("task_metrics") or {}).get("reasons_fail") or []:
            code = reason.split("<")[0].split(">")[0]
            causes.append(
                {
                    "code": code,
                    "detail": reason,
                    "human": FAILURE_CAUSES.get(code, FAILURE_CAUSES.get(reason, reason)),
                }
            )
        if r.get("task_success") is False and not any(c.get("code", "").startswith("task") for c in causes):
            causes.append(
                {
                    "code": "task_success_false",
                    "detail": r.get("task_success_scope"),
                    "human": "北极星 task_success 未达标",
                }
            )
        out.append({"case_id": r["case_id"], "causes": causes})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=_BENCH / "eval_cases" / "dev" / "cases.json")
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--audit", type=Path, default=_BENCH / "results" / "simulation_audit.jsonl")
    ap.add_argument("-o", type=Path, default=_BENCH / "results" / "evaluator_report.json")
    ap.add_argument("--with-deepeval", action="store_true")
    args = ap.parse_args()

    from load_cases import load_eval_cases  # noqa: E402

    cases = load_eval_cases(args.cases)
    audit_rows = _load_jsonl(args.audit)

    rule_out = _BENCH / "results" / "agent_eval_for_evaluator.json"
    proc = subprocess.run(
        [
            _PY,
            str(_BENCH / "run_agent_eval.py"),
            "--cases",
            str(args.cases),
            "--pred",
            str(args.pred),
            "-o",
            str(rule_out),
        ],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rule_report = json.loads(rule_out.read_text(encoding="utf-8")) if rule_out.is_file() else {}
    proc_summary = rule_report.get("process_metrics_summary") or {}
    proc_path = _BENCH / "results" / "process_metrics_report.json"
    if proc_summary:
        proc_path.parent.mkdir(parents=True, exist_ok=True)
        proc_path.write_text(json.dumps(proc_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sim_checks = _check_simulation_consistency(cases, audit_rows)
    sim_failed = [c for c in sim_checks if not c.get("pass")]

    diagnosis = _diagnose(rule_report.get("results") or [])

    deepeval_summary = None
    if args.with_deepeval:
        judge_in = _BENCH / "results" / "judge_from_pred.jsonl"
        preds = _load_jsonl(args.pred)
        judge_in.write_text(
            "".join(
                json.dumps(
                    {
                        "case_id": p["case_id"],
                        "user_text": " ".join(p.get("user_messages") or []),
                        "assistant_text": p.get("assistant_text") or "",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                for p in preds
            ),
            encoding="utf-8",
        )
        dproc = subprocess.run(
            [_PY, str(_BENCH / "run_deepeval_judge.py"), "--input", str(judge_in)],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
        )
        deepeval_summary = {"exit_code": dproc.returncode, "tail": (dproc.stdout or dproc.stderr)[-500:]}

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evaluator": "lifecare_benchmark_v1",
        "references": [
            "DeepEval Agent Metrics: https://docs.confident-ai.com/docs/metrics-introduction",
            "LangSmith Evaluation: https://docs.smith.langchain.com/evaluation",
        ],
        "scale": {
            "agent_rule_cases": len(cases),
            "simulation_audit_rows": len(audit_rows),
        },
        "rule_eval": {
            "passed": rule_report.get("passed"),
            "total": rule_report.get("cases"),
            "path": str(rule_out),
            "task_success_count": rule_report.get("task_success_count"),
            "task_success_rate_pct": rule_report.get("task_success_rate_pct"),
            "planning_task_success_rate_pct": rule_report.get("planning_task_success_rate_pct"),
            "by_difficulty": rule_report.get("by_difficulty"),
            "process_metrics_summary": proc_summary,
            "process_metrics_report": str(proc_path) if proc_summary else None,
            "robustness_task_success_rate": proc_summary.get("robustness_task_success_rate"),
        },
        "simulation_consistency": {
            "checked": len(sim_checks),
            "failed": len(sim_failed),
            "details": sim_checks,
        },
        "failure_diagnosis": diagnosis,
        "deepeval": deepeval_summary,
        "overall_pass": (
            rule_report.get("passed") == rule_report.get("cases")
            and len(sim_failed) == 0
            and not rule_report.get("missing_pred")
        ),
    }
    scorecard_proc = subprocess.run(
        [_PY, str(_BENCH / "build_case_scorecard.py"), "--pred", str(args.pred), "--eval", str(rule_out)],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
    )
    scorecard_path = _BENCH / "results" / "case_scorecard.json"
    if scorecard_path.is_file():
        report["per_case_scorecard"] = str(scorecard_path)
        report["per_case"] = json.loads(scorecard_path.read_text(encoding="utf-8")).get("cases", [])

    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "overall_pass": report["overall_pass"],
                "rule": f"{rule_report.get('passed')}/{rule_report.get('cases')}",
                "sim_fail": len(sim_failed),
                "out": str(args.o),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
