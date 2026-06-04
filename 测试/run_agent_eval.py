#!/usr/bin/env python3
"""
Agent 评测：固定 rubric + 从用户话自动推断适用规则（不需每条 expect）。

用法：
  python benchmark/run_agent_eval.py --pred benchmark/results/agent_pred_live.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parent
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

from load_cases import load_eval_cases  # noqa: E402
from rubric_engine import evaluate_all, load_rubric  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_pred_map(rows: list[dict]) -> dict:
    """兼容 pred 里 case_id 为 int 或 str（含历史字符串别名）。"""
    pred_map: dict = {}
    for r in rows:
        k = r.get("case_id")
        if k is None:
            continue
        pred_map[k] = r
        if isinstance(k, str) and k.isdigit():
            pred_map[int(k)] = r
        elif isinstance(k, int):
            pred_map[str(k)] = r
    return pred_map


def _lookup_pred(pred_map: dict, case_id) -> dict | None:
    return pred_map.get(case_id) or pred_map.get(str(case_id))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=_BENCH / "eval_cases" / "dev" / "cases.json")
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--rubric", type=Path, default=_BENCH / "rubric.json")
    ap.add_argument("-o", type=Path, default=_BENCH / "results" / "agent_eval_latest.json")
    ap.add_argument("--only", type=str, default="", help="逗号分隔 case_id，仅评这些题")
    args = ap.parse_args()

    rubric = load_rubric(args.rubric)
    cases = load_eval_cases(args.cases)
    if args.only.strip():
        allow: set = set()
        for x in args.only.split(","):
            x = x.strip()
            if not x:
                continue
            allow.add(x)
            if x.isdigit():
                allow.add(int(x))
        cases = [c for c in cases if c["case_id"] in allow or str(c["case_id"]) in allow]
    pred_rows = _load_jsonl(args.pred)
    pred_map = _build_pred_map(pred_rows)

    report = evaluate_all(cases, pred_map, rubric)
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scores = [r.get("total_score", 0) for r in report.get("results") or []]
    avg = int(round(sum(scores) / len(scores))) if scores else 0
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "total": report["cases"],
                "avg_total_score": avg,
                "task_success": report.get("task_success_count"),
                "task_success_rate_pct": report.get("task_success_rate_pct"),
                "planning_task_success_rate_pct": report.get("planning_task_success_rate_pct"),
                "by_difficulty": report.get("by_difficulty"),
                "process_metrics": report.get("process_metrics_summary"),
                "robustness_task_success_rate": (report.get("process_metrics_summary") or {}).get(
                    "robustness_task_success_rate"
                ),
                "rubric": str(args.rubric),
                "out": str(args.o),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
