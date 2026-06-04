#!/usr/bin/env python3
"""Launch 6.3 vitabench batch on ECS (remaining tasks)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from remote_vitabench_smoke import (
    fix_ecs_pairing,
    load_config,
    switch_model,
    sync_to_ecs,
    _ssh,
)

_MODEL_SEL = Path(__file__).resolve().parent
_BATCH_RUNNER = _MODEL_SEL / "ecs_v63_batch_runner.py"


def start_batch(
    cfg: dict,
    *,
    model_alias: str,
    thinking: str,
    temperature: str,
    exclude: str,
    dry_run_eval: bool,
    retry_failed: bool = False,
) -> None:
    host = cfg["ecs"]["host"]
    bench = cfg["ecs"]["bench_path"]
    out_dir = f"{bench}/model_selection/results/v63-batch/{model_alias}"
    log = f"{out_dir}/batch.log"
    pid_file = f"{out_dir}/batch.pid"

    subprocess.check_call(
        ["scp", "-o", "BatchMode=yes", str(_BATCH_RUNNER), f"{host}:/tmp/ecs_v63_batch_runner.py"],
        timeout=120,
    )
    judge_flag = " --dry-run-eval" if dry_run_eval else ""
    retry_flag = " --retry-failed" if retry_failed else ""
    remote = (
        f"mkdir -p {out_dir} {bench}/results && "
        f"setsid python3 /tmp/ecs_v63_batch_runner.py "
        f"--model-alias {model_alias} --thinking {thinking} "
        f"--exclude {exclude}{judge_flag}{retry_flag} "
        f"< /dev/null >> {log} 2>&1 & echo $! > {pid_file}; sleep 1; cat {pid_file}"
    )
    proc = _ssh(host, remote, timeout=15)
    if proc.returncode != 0 and proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.stdout.strip():
        print(f"ECS batch pid: {proc.stdout.strip()}")
    print(f"Remote log: {host}:{log}")
    print(f"Progress:   {host}:{out_dir}/batch_progress.json")


def pull_results(cfg: dict, *, model_alias: str) -> Path:
    host = cfg["ecs"]["host"]
    bench = cfg["ecs"]["bench_path"]
    remote_dir = f"{bench}/model_selection/results/v63-batch/{model_alias}"
    local_dir = _MODEL_SEL / "results" / "v63-batch" / model_alias
    local_dir.mkdir(parents=True, exist_ok=True)
    for name in ("batch_summary.json", "batch_progress.json", "batch.log"):
        try:
            subprocess.check_call(
                ["scp", "-o", "BatchMode=yes", f"{host}:{remote_dir}/{name}", str(local_dir / name)],
                timeout=120,
            )
        except subprocess.CalledProcessError:
            pass
    proc = _ssh(host, f"ls {remote_dir}/*_run.json 2>/dev/null | wc -l", timeout=30)
    count = proc.stdout.strip()
    print(f"Remote run files: {count}")
    if count.isdigit() and int(count) > 0:
        subprocess.check_call(
            [
                "scp",
                "-o",
                "BatchMode=yes",
                f"{host}:{remote_dir}/*_run.json",
                str(local_dir) + "/",
            ],
            timeout=600,
        )
        subprocess.check_call(
            [
                "scp",
                "-o",
                "BatchMode=yes",
                f"{host}:{remote_dir}/*_eval_detail.json",
                str(local_dir) + "/",
            ],
            timeout=600,
        )
    return local_dir


def show_status(cfg: dict, *, model_alias: str) -> None:
    host = cfg["ecs"]["host"]
    bench = cfg["ecs"]["bench_path"]
    out_dir = f"{bench}/model_selection/results/v63-batch/{model_alias}"
    proc = _ssh(
        host,
        f"test -f {out_dir}/batch.pid && ps -p $(cat {out_dir}/batch.pid) >/dev/null 2>&1 && echo RUNNING || echo STOPPED; "
        f"test -f {out_dir}/batch_progress.json && python3 -c \"import json; s=json.load(open('{out_dir}/batch_progress.json')); print('done', sum(1 for x in s if x.get('ok')), '/', len(s))\" 2>/dev/null; "
        f"tail -n 5 {out_dir}/batch.log 2>/dev/null",
        timeout=30,
    )
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)


def kill_stale_batch(cfg: dict, *, model_alias: str) -> None:
    host = cfg["ecs"]["host"]
    _ssh(host, "pkill -f ecs_v63_batch_runner.py || true", timeout=30)
    print("stopped stale batch processes on ECS", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="6.3 ECS batch (49 remaining tasks)")
    ap.add_argument("--model", default="qwen")
    ap.add_argument("--temperature", default="0.0")
    ap.add_argument("--thinking", default="medium")
    ap.add_argument("--exclude", default="T063_007", help="skip already-done tasks")
    ap.add_argument("--dry-run-eval", action="store_true")
    ap.add_argument("--retry-failed", action="store_true", help="re-run LLM-failed tasks from batch_progress")
    ap.add_argument("--resume", action="store_true", help="kill stale batch and continue without model switch")
    ap.add_argument("--skip-sync", action="store_true")
    ap.add_argument("--pull", action="store_true", help="pull results from ECS")
    ap.add_argument("--status", action="store_true", help="show batch status on ECS")
    ap.add_argument("--wait", action="store_true", help="poll until batch stops")
    args = ap.parse_args()

    cfg = load_config()
    if args.status:
        show_status(cfg, model_alias=args.model)
        return
    if args.pull:
        local = pull_results(cfg, model_alias=args.model)
        summary = local / "batch_summary.json"
        if summary.is_file():
            print(summary.read_text(encoding="utf-8"))
        return

    if not args.skip_sync:
        print("syncing to ECS...", flush=True)
        sync_to_ecs(cfg)
    if args.resume or not args.skip_sync:
        kill_stale_batch(cfg, model_alias=args.model)
    if not args.resume:
        print(f"switching model {args.model}...", flush=True)
        switch_model(args.model, temperature=args.temperature, thinking=args.thinking)
        fix_ecs_pairing(cfg)
    else:
        print("resume: skip model switch, only run remaining tasks", flush=True)
        fix_ecs_pairing(cfg)
    start_batch(
        cfg,
        model_alias=args.model,
        thinking=args.thinking,
        temperature=args.temperature,
        exclude=args.exclude,
        dry_run_eval=args.dry_run_eval,
        retry_failed=args.retry_failed or args.resume,
    )

    if args.wait:
        print("polling batch status (Ctrl+C to stop polling)...", flush=True)
        while True:
            host = cfg["ecs"]["host"]
            bench = cfg["ecs"]["bench_path"]
            out_dir = f"{bench}/model_selection/results/v63-batch/{args.model}"
            proc = _ssh(
                host,
                f"test -f {out_dir}/batch.pid && ps -p $(cat {out_dir}/batch.pid) >/dev/null 2>&1 && echo RUNNING || echo STOPPED",
                timeout=30,
            )
            state = proc.stdout.strip()
            show_status(cfg, model_alias=args.model)
            if state == "STOPPED":
                break
            time.sleep(120)
        pull_results(cfg, model_alias=args.model)


if __name__ == "__main__":
    main()
