#!/usr/bin/env python3
"""Run one or more 6.3 VitaBench-style tasks."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_BENCH = Path(__file__).resolve().parent.parent
_MODEL_SEL = _BENCH / "模型选型"
_REPO = _BENCH.parent
for p in (_BENCH, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from vitabench_eval.load_tasks import load_task, tasks_dir  # noqa: E402
from vitabench_eval.llm_client import load_repo_env  # noqa: E402
from vitabench_eval.orchestrator import run_simulation  # noqa: E402
from vitabench_eval.task_schema import validate_task  # noqa: E402


def _load_v63_config() -> dict:
    cfg_path = _MODEL_SEL / "config.json"
    if not cfg_path.is_file():
        return {}
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    return data.get("v63") or {}


def main() -> None:
    ap = argparse.ArgumentParser(description="6.3 vitabench eval")
    ap.add_argument("--task-id", default="T063_007")
    ap.add_argument("--tasks-dir", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--session-prefix", default="v63")
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--max-errors", type=int, default=0)
    ap.add_argument("--agent-timeout-s", type=int, default=0)
    ap.add_argument("--dry-run-eval", action="store_true")
    ap.add_argument("--skip-agent", action="store_true")
    ap.add_argument("--user-model", default="user")
    ap.add_argument("--judge-model", default="judge")
    args = ap.parse_args()

    load_repo_env()
    v63 = _load_v63_config()
    orch = v63.get("orchestrator") or {}
    llm = v63.get("llm") or {}

    root = tasks_dir(args.tasks_dir or v63.get("tasks_dir") or None)
    task = load_task(args.task_id, tasks_root=root)
    errs = validate_task(task)
    if errs:
        raise SystemExit("invalid task: " + "; ".join(errs))
    print(f"loaded task {task['id']} from {root}", flush=True)

    if args.skip_agent:
        print(json.dumps({"task_id": task["id"], "ok": True}, ensure_ascii=False))
        return

    result = run_simulation(
        task,
        session_prefix=args.session_prefix,
        max_steps=args.max_steps or orch.get("max_steps", 100),
        max_errors=args.max_errors or orch.get("max_errors", 10),
        agent_timeout_s=args.agent_timeout_s or orch.get("agent_timeout_s", 180),
        skip_judge=args.dry_run_eval,
        user_model=args.user_model,
        judge_model=args.judge_model,
        user_temperature=(llm.get("user_simulator") or {}).get("temperature"),
        judge_temperature=(llm.get("evaluator") or {}).get("temperature"),
    )
    payload = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "task_id": task["id"],
        "pipeline": "vitabench_eval_v63",
        **result,
    }
    out_dir = Path(args.out).parent if args.out else _BENCH / "vitabench_eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_path = Path(args.out) if args.out else out_dir / f"{task['id']}_run.json"
    run_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    eval_detail = {
        "task_id": task["id"],
        "termination": result.get("termination"),
        "reward": (result.get("reward_info") or {}).get("reward"),
        "rubric_states": (result.get("reward_info") or {}).get("rubric_states"),
        "first_response": result.get("first_response"),
    }
    detail_path = out_dir / f"{task['id']}_eval_detail.json"
    detail_path.write_text(json.dumps(eval_detail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {run_path}", flush=True)
    print(f"wrote {detail_path}", flush=True)


if __name__ == "__main__":
    main()
