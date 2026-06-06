#!/usr/bin/env python3
"""Launch §10 harness 10-task 6.3 batch on ECS."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from remote_vitabench_batch import pull_results, show_status, start_batch
from remote_vitabench_smoke import fix_ecs_pairing, load_config, switch_model, sync_to_ecs, _ssh

_MODEL_SEL = Path(__file__).resolve().parent
_ROOT = _MODEL_SEL.parent.parent
_APPLY = _ROOT / "gateway-chat-ui" / "scripts" / "ecs_apply_lifecare_openclaw.py"
_BATCH_RUNNER = _MODEL_SEL / "ecs_v63_batch_runner.py"

TASK_IDS = [
    "T063_002",
    "T063_005",
    "T063_010",
    "T063_SAMPLE_001",
    "T063_015",
    "T063_020",
    "T063_030",
    "T063_035",
    "T063_045",
    "T063_050",
]
MODEL_ALIAS = "qwen-harness10"


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-sync", action="store_true")
    ap.add_argument("--skip-apply", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    host = cfg["ecs"]["host"]
    if args.status:
        show_status(cfg, model_alias=MODEL_ALIAS)
        return
    if args.pull:
        local = pull_results(cfg, model_alias=MODEL_ALIAS)
        _print_summary(local)
        return

    if not args.skip_sync:
        print("syncing vitabench_eval + harness + tasks to ECS...", flush=True)
        sync_to_ecs(cfg)
    print("switching qwen temp=0.0 thinking=medium...", flush=True)
    switch_model("qwen", temperature="0.0", thinking="medium")
    if not args.skip_apply:
        print("applying workspace to ~/.openclaw on ECS...", flush=True)
        repo = cfg["ecs"]["repo_path"]
        proc = _ssh(
            host,
            f"python3 {repo}/gateway-chat-ui/scripts/ecs_apply_lifecare_openclaw.py",
            timeout=120,
        )
        if proc.stdout.strip():
            print(proc.stdout.strip())
        if proc.returncode != 0:
            raise RuntimeError(f"ecs_apply failed: {proc.stderr or proc.stdout}")
    fix_ecs_pairing(cfg)

    bench = cfg["ecs"]["bench_path"]
    out_dir = f"{bench}/model_selection/results/v63-batch/{MODEL_ALIAS}"
    log = f"{out_dir}/batch.log"
    pid_file = f"{out_dir}/batch.pid"
    task_csv = ",".join(TASK_IDS)

    subprocess.check_call(
        ["scp", "-o", "BatchMode=yes", str(_BATCH_RUNNER), f"{host}:/tmp/ecs_v63_batch_runner.py"],
        timeout=120,
    )
    _ssh(host, "pkill -f ecs_v63_batch_runner.py || true", timeout=30)
    remote = (
        f"mkdir -p {out_dir} {bench}/results && "
        f"setsid python3 /tmp/ecs_v63_batch_runner.py "
        f"--model-alias {MODEL_ALIAS} --thinking medium "
        f"--task-ids {task_csv} "
        f"< /dev/null >> {log} 2>&1 & echo $! > {pid_file}; sleep 1; cat {pid_file}"
    )
    proc = _ssh(host, remote, timeout=20)
    print(f"ECS batch pid: {proc.stdout.strip()}")
    print(f"Remote log: {host}:{log}")
    print(f"Tasks ({len(TASK_IDS)}): {task_csv}")

    if args.wait:
        import time

        print("polling until batch completes...", flush=True)
        while True:
            proc = _ssh(
                host,
                f"test -f {pid_file} && ps -p $(cat {pid_file}) >/dev/null 2>&1 && echo RUNNING || echo STOPPED",
                timeout=30,
            )
            show_status(cfg, model_alias=MODEL_ALIAS)
            if proc.stdout.strip() == "STOPPED":
                break
            time.sleep(120)
        local = pull_results(cfg, model_alias=MODEL_ALIAS)
        _print_summary(local)


def _print_summary(local: Path) -> None:
    summary = local / "batch_summary.json"
    if not summary.is_file():
        print("no batch_summary.json yet")
        return
    import json

    data = json.loads(summary.read_text(encoding="utf-8"))
    rows = data.get("results") or []
    rewards = [r.get("reward") for r in rows if r.get("ok") and r.get("reward") is not None]
    print(f"\n=== {MODEL_ALIAS} summary ===")
    print(f"ok: {data.get('ok_count')}/{data.get('total')}")
    if rewards:
        print(f"avg reward: {sum(rewards)/len(rewards):.3f}")
        print(f"rewards: {rewards}")
    for r in rows:
        print(
            f"  {r.get('task_id')}: ok={r.get('ok')} reward={r.get('reward')} "
            f"termination={r.get('termination')} skipped={r.get('skipped')}"
        )


if __name__ == "__main__":
    main()
