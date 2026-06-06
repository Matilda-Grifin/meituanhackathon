#!/usr/bin/env python3
"""SSH ECS: sync 6.3 vitabench eval → switch agent model → run 1 task (full pipeline)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_MODEL_SEL = Path(__file__).resolve().parent
_BENCH = _MODEL_SEL.parent
_ROOT = _BENCH.parent
_V63_DATA = _ROOT.parent / "待修复" / "模型选型评测" / "data"
_SWITCH = _ROOT / "gateway-chat-ui" / "scripts" / "run_ecs_switch_model_from_local_env.py"


def load_config() -> dict:
    return json.loads((_MODEL_SEL / "config.json").read_text(encoding="utf-8"))


def _ssh(host: str, cmd: str, *, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def fix_ecs_pairing(cfg: dict) -> None:
    host = cfg["ecs"]["host"]
    fix_script = Path(__file__).resolve().parent / "ecs_fix_pairing.py"
    if fix_script.is_file():
        subprocess.check_call(
            ["scp", "-o", "BatchMode=yes", str(fix_script), f"{host}:/tmp/ecs_fix_pairing.py"],
            timeout=120,
        )
        proc = _ssh(host, "python3 /tmp/ecs_fix_pairing.py", timeout=60)
    else:
        proc = _ssh(host, "test -d /root/.openclaw/npm/node_modules/@openclaw/feishu.disabled || mv /root/.openclaw/npm/node_modules/@openclaw/feishu /root/.openclaw/npm/node_modules/@openclaw/feishu.disabled 2>/dev/null; echo ok", timeout=60)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)


def sync_to_ecs(cfg: dict) -> None:
    host = cfg["ecs"]["host"]
    bench = cfg["ecs"]["bench_path"]
    repo = cfg["ecs"]["repo_path"]
    tasks_remote = f"{bench}/eval_cases/vitabench"
    _ssh(host, f"mkdir -p {tasks_remote}/tasks {bench}/model_selection/results/v63-smoke {bench}/model_selection/results/v63-batch {repo}/lifecare")

    for rel in [
        _BENCH / "vitabench_eval",
        _MODEL_SEL / "config.json",
    ]:
        dest = f"{host}:{bench}/" if rel.name == "vitabench_eval" else f"{host}:{bench}/model_selection/"
        if rel.name == "vitabench_eval":
            subprocess.check_call(["scp", "-r", "-o", "BatchMode=yes", str(rel), dest])
        else:
            subprocess.check_call(["scp", "-o", "BatchMode=yes", str(rel), dest])

    subprocess.check_call(
        ["scp", "-o", "BatchMode=yes", str(_ROOT / "run_mcp.py"), f"{host}:{repo}/"]
    )
    harness = _ROOT / "lifecare" / "harness"
    if harness.is_dir():
        subprocess.check_call(
            ["scp", "-r", "-o", "BatchMode=yes", str(harness), f"{host}:{repo}/lifecare/"]
        )
    subprocess.check_call(
        ["scp", "-o", "BatchMode=yes", str(_ROOT / "lifecare" / "mcp_tool_log.py"), f"{host}:{repo}/lifecare/"]
    )
    soul = _ROOT / "workspace" / "SOUL.md"
    if soul.is_file():
        subprocess.check_call(
            ["scp", "-o", "BatchMode=yes", str(soul), f"{host}:{repo}/workspace/"]
        )
    skill = _ROOT / "workspace" / "skills" / "local-itinerary-planner" / "SKILL.md"
    if skill.is_file():
        _ssh(
            host,
            f"mkdir -p {repo}/workspace/skills/local-itinerary-planner {repo}/.openclaw/workspace/skills/local-itinerary-planner 2>/dev/null; true",
        )
        subprocess.check_call(
            [
                "scp",
                "-o",
                "BatchMode=yes",
                str(skill),
                f"{host}:{repo}/workspace/skills/local-itinerary-planner/",
            ]
        )
    subprocess.check_call(
        ["scp", "-r", "-o", "BatchMode=yes", str(_V63_DATA / "tasks"), f"{host}:{tasks_remote}/"]
    )
    subprocess.check_call(
        ["scp", "-o", "BatchMode=yes", str(_V63_DATA / "manifest.json"), f"{host}:{tasks_remote}/"]
    )
    env_file = _ROOT.parent / ".env"
    if env_file.is_file():
        subprocess.check_call(
            ["scp", "-o", "BatchMode=yes", str(env_file), f"{host}:/root/meituan-lifecare-agent/.env"]
        )


def switch_model(model_alias: str, *, temperature: str = "0.0", thinking: str = "medium") -> None:
    env = os.environ.copy()
    env["V63_EVAL_TEMPERATURE"] = temperature
    env["V63_EVAL_THINKING"] = thinking
    subprocess.check_call(
        [sys.executable, str(_SWITCH), model_alias, "--restart-gateway"],
        cwd=str(_ROOT),
        env=env,
    )


def run_smoke(
    cfg: dict,
    *,
    task_id: str,
    model_alias: str,
    thinking: str = "medium",
    dry_run_eval: bool = False,
) -> dict:
    host = cfg["ecs"]["host"]
    bench = cfg["ecs"]["bench_path"]
    out_dir = f"{bench}/model_selection/results/v63-smoke/{model_alias}"
    run_file = f"{out_dir}/{task_id}_run.json"
    detail_file = f"{out_dir}/{task_id}_eval_detail.json"
    judge_flag = " --dry-run-eval" if dry_run_eval else ""
    remote_cmd = (
        f"mkdir -p {out_dir} {bench}/results && cd {bench} && "
        f"export PYTHONPATH={cfg['ecs']['repo_path']}:{bench} && "
        f"export V63_TASKS_DIR={bench}/eval_cases/vitabench/tasks && "
        f"export LIFECARE_MCP_TOOL_LOG=1 && "
        f"export LIFECARE_MCP_TOOL_LOG_PATH={bench}/results/mcp_tool_calls.jsonl && "
        f"export V63_EVAL_THINKING={thinking} && "
        f"export V63_AGENT_LOCAL=0 && "
        f"python3 vitabench_eval/run_benchmark.py --task-id {task_id} "
        f"--agent-timeout-s 420 --out {run_file}{judge_flag}"
    )
    proc = _ssh(host, remote_cmd, timeout=900)
    if proc.stdout:
        try:
            print(proc.stdout)
        except UnicodeEncodeError:
            print(proc.stdout.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"remote smoke failed (code {proc.returncode})")
    local_out = _MODEL_SEL / "results" / "v63-smoke"
    local_out.mkdir(parents=True, exist_ok=True)
    local_run = local_out / f"{model_alias}_{task_id}_run.json"
    subprocess.check_call(["scp", "-o", "BatchMode=yes", f"{host}:{run_file}", str(local_run)])
    local_detail = local_out / f"{model_alias}_{task_id}_eval_detail.json"
    try:
        subprocess.check_call(
            ["scp", "-o", "BatchMode=yes", f"{host}:{detail_file}", str(local_detail)]
        )
    except subprocess.CalledProcessError:
        pass
    return json.loads(local_run.read_text(encoding="utf-8"))


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen")
    ap.add_argument("--task-id", default="T063_007")
    ap.add_argument("--temperature", default="0.0")
    ap.add_argument("--thinking", default="medium")
    ap.add_argument("--dry-run-eval", action="store_true")
    ap.add_argument("--skip-sync", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if not args.skip_sync:
        print("syncing vitabench_eval + MCP + tasks to ECS...", flush=True)
        sync_to_ecs(cfg)
    print(f"switching ECS agent to {args.model} temp={args.temperature} thinking={args.thinking}...", flush=True)
    switch_model(args.model, temperature=args.temperature, thinking=args.thinking)
    print("fixing ECS device pairing / feishu plugin...", flush=True)
    fix_ecs_pairing(cfg)
    print(f"running full pipeline task {args.task_id}...", flush=True)
    result = run_smoke(
        cfg,
        task_id=args.task_id,
        model_alias=args.model,
        thinking=args.thinking,
        dry_run_eval=args.dry_run_eval,
    )
    summary = {
        "ok": True,
        "task_id": result.get("task_id"),
        "termination": result.get("termination"),
        "steps": result.get("steps"),
        "num_errors": result.get("num_errors"),
        "reward": (result.get("reward_info") or {}).get("reward"),
        "rubric_met": (result.get("reward_info") or {}).get("rubric_met"),
        "first_response": result.get("first_response"),
        "trajectory_turns": len(result.get("trajectory") or []),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
