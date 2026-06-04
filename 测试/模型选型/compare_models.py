#!/usr/bin/env python3
"""汇总一次 run_id 下各模型 eval + 多轮指标，生成决策矩阵 JSON。"""
from __future__ import annotations

import json
from pathlib import Path

_SKIP_DIR_NAMES = frozenset({"figures", "comparison.json", "__pycache__"})


def _is_model_result_dir(model_dir: Path) -> bool:
    if not model_dir.is_dir() or model_dir.name in _SKIP_DIR_NAMES or model_dir.name.startswith("."):
        return False
    return any((model_dir / f"eval_{ds}.json").is_file() for ds in ("singleturn", "multiturn"))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _summarize_preds(model_dir: Path) -> dict[str, dict]:
    """从轨迹文件汇总 Token、工具次数、首响耗时（有则统计）。"""
    out: dict[str, dict] = {}
    for ds in ("singleturn", "multiturn"):
        preds = _load_jsonl(model_dir / f"pred_{ds}.jsonl")
        if not preds:
            continue
        total_tokens = 0
        tool_calls = 0
        latencies: list[float] = []
        for p in preds:
            u = p.get("token_usage") or {}
            total_tokens += int(u.get("total_tokens") or 0)
            tool_calls += len(p.get("tools_in_order") or [])
            for t in p.get("turns") or []:
                tool_calls += len(t.get("tools") or [])
            lat = p.get("latency_first_token_ms")
            if lat is not None:
                latencies.append(float(lat))
        n = len(preds) or 1
        out[ds] = {
            "cases": len(preds),
            "total_tokens": total_tokens,
            "avg_tokens_per_case": round(total_tokens / n, 1) if total_tokens else None,
            "avg_tool_calls_per_case": round(tool_calls / n, 2),
            "avg_first_response_ms": int(round(sum(latencies) / len(latencies))) if latencies else None,
        }
    return out


def build_comparison(run_dir: Path) -> dict:
    rows = []
    for model_dir in sorted(run_dir.iterdir()):
        if not _is_model_result_dir(model_dir):
            continue
        alias = model_dir.name
        row: dict = {"model": alias}
        for ds in ("singleturn", "multiturn"):
            eval_path = model_dir / f"eval_{ds}.json"
            if eval_path.is_file():
                ev = json.loads(eval_path.read_text(encoding="utf-8"))
                row[f"{ds}_task_success_rate_pct"] = ev.get("task_success_rate_pct")
                row[f"{ds}_avg_score"] = _avg_score(ev)
                row[f"{ds}_passed"] = ev.get("passed")
                row[f"{ds}_total"] = ev.get("cases")
                by_diff = ev.get("by_difficulty") or {}
                for diff in ("easy", "medium", "hard"):
                    if diff in by_diff:
                        row[f"{ds}_{diff}_task_success_rate_pct"] = by_diff[diff].get(
                            "task_success_rate_pct"
                        )
            mt_path = model_dir / "multiturn_metrics.json"
            if mt_path.is_file():
                mt = json.loads(mt_path.read_text(encoding="utf-8"))
                row["multiturn_history_constraint_rate"] = mt.get("history_constraint_rate_avg")
                row["multiturn_followup_efficiency_rate"] = mt.get("followup_efficiency_rate_avg")
                row["multiturn_replan_success_rate"] = mt.get("replan_success_rate")
                row["multiturn_tool_compliance_rate"] = mt.get("tool_compliance_rate_avg")
                row["multiturn_execution_success_rate"] = mt.get("execution_success_rate")
        pred_stats = _summarize_preds(model_dir)
        for ds, stats in pred_stats.items():
            row[f"{ds}_total_tokens"] = stats.get("total_tokens")
            row[f"{ds}_avg_tokens_per_case"] = stats.get("avg_tokens_per_case")
            row[f"{ds}_avg_tool_calls_per_case"] = stats.get("avg_tool_calls_per_case")
            row[f"{ds}_avg_first_response_ms"] = stats.get("avg_first_response_ms")
        rows.append(row)
    return {"models": rows, "run_dir": str(run_dir)}


def _avg_score(eval_report: dict) -> int:
    scores = [r.get("total_score", 0) for r in eval_report.get("results") or []]
    return int(round(sum(scores) / len(scores))) if scores else 0


if __name__ == "__main__":
    import sys

    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results"
    print(json.dumps(build_comparison(run_dir), ensure_ascii=False, indent=2))
