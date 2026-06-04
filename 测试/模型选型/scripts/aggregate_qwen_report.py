#!/usr/bin/env python3
"""Aggregate qwen v63 results for HTML report."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "results" / "v63-batch" / "qwen"
MANIFEST = Path(__file__).resolve().parents[3].parent / "待修复" / "模型选型评测" / "data" / "manifest.json"
SMOKE = ROOT / "results" / "v63-smoke" / "qwen_T063_007_run.json"


def load_manifest() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data.get("tasks") or []


def load_run(task_id: str) -> dict | None:
    p = BATCH / f"{task_id}_run.json"
    if not p.is_file() and task_id == "T063_007" and SMOKE.is_file():
        p = SMOKE
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _agent_error_detail(run: dict) -> str | None:
    if run.get("termination") != "agent_error":
        return None
    for m in run.get("trajectory") or []:
        if m.get("error"):
            return str(m["error"])
        if "[agent_error]" in (m.get("content") or ""):
            return (m.get("content") or "").replace("[agent_error]", "").strip()
    return None


def _ttft_ms(run: dict) -> int | None:
    for m in run.get("trajectory") or []:
        if m.get("role") == "assistant":
            t = m.get("time_to_first_assistant_text_ms") or m.get("time_to_first_progress_ms")
            if t is not None:
                return int(t)
    return None


def main() -> None:
    tasks = load_manifest()
    rows = []
    for t in tasks:
        tid = t["id"]
        run = load_run(tid)
        if not run:
            rows.append({"id": tid, "missing": True})
            continue
        ri = run.get("reward_info") or {}
        fr = run.get("first_response") or {}
        term = run.get("termination") or "unknown"
        reward = ri.get("reward")
        if reward is None:
            reward = 0.0
        err = _agent_error_detail(run)
        err_kind = None
        if err:
            if "timeout" in err.lower():
                err_kind = "timeout"
            elif "message" in err.lower() and "required" in err.lower():
                err_kind = "empty_message"
            else:
                err_kind = "other"
        rows.append(
            {
                "id": tid,
                "scenario": t.get("scenario", ""),
                "difficulty": t.get("difficulty", ""),
                "city": t.get("city", ""),
                "trip_mode": t.get("trip_mode", ""),
                "rubric_count": t.get("rubric_count"),
                "termination": term,
                "steps": run.get("steps"),
                "num_errors": run.get("num_errors"),
                "reward": reward,
                "full_success": ri.get("full_success") or (reward >= 1.0 if ri.get("rubric_total") else False),
                "rubric_met": ri.get("rubric_met"),
                "rubric_total": ri.get("rubric_total"),
                "first_response_score": fr.get("score"),
                "first_response_reason": fr.get("reason"),
                "ttft_ms": _ttft_ms(run),
                "agent_error": err,
                "agent_error_kind": err_kind,
                "missing": False,
            }
        )
    out = BATCH / "report_stats.json"
    out.write_text(json.dumps({"tasks": tasks, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = [r["id"] for r in rows if r.get("missing")]
    print("total", len(rows), "missing", len(missing))


if __name__ == "__main__":
    main()
