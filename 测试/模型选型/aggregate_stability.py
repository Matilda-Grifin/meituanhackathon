#!/usr/bin/env python3
"""
汇总同一模型、同一批难题、多次运行的稳定性（Pass@3 / 全中率）。

用法（先各跑一遍，再汇总）：
  python 模型选型/aggregate_stability.py --model doubao --runs 20260602-stab-r1,20260602-stab-r2,20260602-stab-r3
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

_MODEL_SEL = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", required=True, help="逗号分隔的 run_id")
    ap.add_argument("--dataset", default="singleturn")
    args = ap.parse_args()

    subset = json.loads((_MODEL_SEL / "stability_subset.json").read_text(encoding="utf-8"))
    case_ids = set(subset["case_ids"])

    by_case: dict[int, list[bool]] = defaultdict(list)
    run_ids = [x.strip() for x in args.runs.split(",") if x.strip()]
    for run_id in run_ids:
        eval_path = _MODEL_SEL / "results" / run_id / args.model / f"eval_{args.dataset}.json"
        if not eval_path.is_file():
            print(f"missing: {eval_path}", flush=True)
            return 1
        ev = json.loads(eval_path.read_text(encoding="utf-8"))
        seen = set()
        for r in ev.get("results") or []:
            cid = r.get("case_id")
            if cid not in case_ids:
                continue
            seen.add(cid)
            by_case[cid].append(bool(r.get("task_success")))
        missing = case_ids - seen
        if missing:
            print(f"warn {run_id}: missing cases {sorted(missing)}", flush=True)

    if not by_case:
        print("no overlapping results", flush=True)
        return 1

    pass_at_3 = pass_all_3 = 0
    details = []
    for cid in sorted(by_case):
        wins = by_case[cid]
        at_least_one = any(wins)
        all_three = len(wins) >= 3 and all(wins[:3])
        if at_least_one:
            pass_at_3 += 1
        if all_three:
            pass_all_3 += 1
        details.append({"case_id": cid, "runs": wins, "any_success": at_least_one, "all_success": all_three})

    n = len(details)
    summary = {
        "model": args.model,
        "run_ids": run_ids,
        "cases": n,
        "pass_at_3_rate_pct": round(100 * pass_at_3 / n, 1),
        "pass_all_3_rate_pct": round(100 * pass_all_3 / n, 1),
        "details": details,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
