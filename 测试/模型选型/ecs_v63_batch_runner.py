#!/usr/bin/env python3
"""Run 6.3 vitabench eval tasks on ECS (executed remotely)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path("/root/meituan-lifecare-agent/benchmark")
REPO = Path("/root/meituan-lifecare-agent")
MANIFEST = BENCH / "eval_cases/vitabench/manifest.json"
MCP_LOG = BENCH / "results/mcp_tool_calls.jsonl"


def _env(model_alias: str, thinking: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
    env["PYTHONPATH"] = f"{REPO}:{BENCH}"
    env["V63_TASKS_DIR"] = str(BENCH / "eval_cases/vitabench/tasks")
    env["LIFECARE_MCP_TOOL_LOG"] = "1"
    env["LIFECARE_MCP_TOOL_LOG_PATH"] = str(MCP_LOG)
    env["V63_EVAL_THINKING"] = thinking
    env["V63_AGENT_LOCAL"] = "0"
    return env


def _load_task_ids(exclude: set[str]) -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = [t["id"] for t in data.get("tasks") or [] if t.get("id")]
    return [tid for tid in ids if tid not in exclude]


def _has_run_artifact(task_id: str, out_dir: Path) -> bool:
    run_file = out_dir / f"{task_id}_run.json"
    if not run_file.is_file():
        return False
    try:
        data = json.loads(run_file.read_text(encoding="utf-8"))
        return bool(data.get("task_id") and data.get("termination"))
    except json.JSONDecodeError:
        return False


def _clear_artifacts(task_id: str, out_dir: Path) -> None:
    for name in (f"{task_id}_run.json", f"{task_id}_eval_detail.json"):
        p = out_dir / name
        if p.is_file():
            p.unlink()


def _failed_task_ids(progress: list[dict]) -> set[str]:
    return {r["task_id"] for r in progress if r.get("task_id") and r.get("ok") is False}


def _run_one(
    task_id: str,
    out_dir: Path,
    *,
    thinking: str,
    dry_run_eval: bool,
    force: bool = False,
    batch: str = "",
) -> dict:
    run_file = out_dir / f"{task_id}_run.json"
    if force:
        _clear_artifacts(task_id, out_dir)
    elif _has_run_artifact(task_id, out_dir):
        existing = json.loads(run_file.read_text(encoding="utf-8"))
        return {
            "task_id": task_id,
            "ok": True,
            "skipped": True,
            "termination": existing.get("termination"),
            "reward": (existing.get("reward_info") or {}).get("reward"),
        }
    MCP_LOG.parent.mkdir(parents=True, exist_ok=True)
    if MCP_LOG.is_file():
        MCP_LOG.write_text("", encoding="utf-8")
    cmd = [
        sys.executable,
        str(BENCH / "vitabench_eval/run_benchmark.py"),
        "--task-id",
        task_id,
        "--agent-timeout-s",
        "420",
        "--out",
        str(run_file),
        "--batch",
        batch,
    ]
    if dry_run_eval:
        cmd.append("--dry-run-eval")
    proc = subprocess.run(
        cmd,
        cwd=str(BENCH),
        env=_env("", thinking),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return {
            "task_id": task_id,
            "ok": False,
            "error": (proc.stderr or proc.stdout or f"exit {proc.returncode}")[:500],
        }
    data = json.loads(run_file.read_text(encoding="utf-8"))
    return {
        "task_id": task_id,
        "ok": True,
        "termination": data.get("termination"),
        "steps": data.get("steps"),
        "reward": (data.get("reward_info") or {}).get("reward"),
        "rubric_met": (data.get("reward_info") or {}).get("rubric_met"),
        "rubric_total": (data.get("reward_info") or {}).get("rubric_total"),
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--model-alias", default="qwen")
    ap.add_argument("--thinking", default="medium")
    ap.add_argument("--exclude", default="T063_007", help="comma-separated task ids to skip")
    ap.add_argument("--dry-run-eval", action="store_true")
    ap.add_argument("--retry-failed", action="store_true", help="re-run tasks marked ok=false in batch_progress.json")
    ap.add_argument("--task-id", default="", help="run single task only")
    ap.add_argument(
        "--task-ids",
        default="",
        help="comma-separated task ids (overrides manifest minus exclude)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-run even if run.json exists (use with --task-id / --task-ids)",
    )
    args = ap.parse_args()

    exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}
    out_dir = BENCH / "model_selection/results/v63-batch" / args.model_alias
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_path = out_dir / "batch_progress.json"
    summary_path = out_dir / "batch_summary.json"

    if args.task_ids.strip():
        task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()]
    elif args.task_id:
        task_ids = [args.task_id]
    else:
        task_ids = _load_task_ids(exclude)

    started = datetime.now(timezone.utc).isoformat()
    summary: list[dict] = []
    if progress_path.is_file():
        try:
            summary = json.loads(progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = []
    done_ids = {tid for tid in task_ids if _has_run_artifact(tid, out_dir)}
    retry_ids: set[str] = set()
    if args.retry_failed:
        retry_ids = _failed_task_ids(summary) & set(task_ids)
        done_ids -= retry_ids
        if retry_ids:
            print(f"retry_failed: {sorted(retry_ids)}", flush=True)
    if args.force:
        done_ids -= set(task_ids)
        print(f"force: re-run {task_ids}", flush=True)

    print(f"batch start: {len(task_ids)} tasks, exclude={exclude}, out={out_dir}", flush=True)
    print(
        f"already have run.json: {len(done_ids)}, retry: {len(retry_ids)}, "
        f"to_run: {len(task_ids) - len(done_ids)}",
        flush=True,
    )
    for i, tid in enumerate(task_ids, 1):
        force = tid in retry_ids or args.force
        if tid in done_ids and not force:
            print(f"[{i}/{len(task_ids)}] skip (run.json exists) {tid}", flush=True)
            continue
        print(f"[{i}/{len(task_ids)}] running {tid}{' (retry)' if force else ''}...", flush=True)
        try:
            row = _run_one(
                tid,
                out_dir,
                thinking=args.thinking,
                dry_run_eval=args.dry_run_eval,
                force=force,
                batch=args.model_alias,
            )
        except Exception as e:
            row = {"task_id": tid, "ok": False, "error": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        summary = [r for r in summary if r.get("task_id") != tid] + [row]
        progress_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  -> {row}", flush=True)
        time.sleep(2)

    payload = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "model_alias": args.model_alias,
        "thinking": args.thinking,
        "exclude": sorted(exclude),
        "total": len(task_ids),
        "ok_count": sum(1 for r in summary if r.get("ok")),
        "results": summary,
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {summary_path}", flush=True)


if __name__ == "__main__":
    main()
