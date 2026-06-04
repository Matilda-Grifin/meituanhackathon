#!/usr/bin/env python3
"""SSH 到 ECS：同步脚本 → 切模型 → collect_openclaw_pred → 拉回 pred/eval。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[1]
_MODEL_SEL = Path(__file__).resolve().parent
_ROOT = _BENCH.parent
_SWITCH = _ROOT / "gateway-chat-ui" / "scripts" / "run_ecs_switch_model_from_local_env.py"


def load_config() -> dict:
    return json.loads((_MODEL_SEL / "config.json").read_text(encoding="utf-8"))


def _remote_selection(cfg: dict) -> str:
    return f"{cfg['ecs']['bench_path']}/{cfg['ecs']['selection_subdir']}"


def _cases_remote(cfg: dict, dataset: str) -> str:
    ds = cfg["datasets"][dataset]
    return ds.get("remote_path") or ds["path"]


def _ssh(cfg: dict, cmd: str) -> subprocess.CompletedProcess:
    host = cfg["ecs"]["host"]
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _ensure_remote_dirs(cfg: dict) -> None:
    bench = cfg["ecs"]["bench_path"]
    sel = _remote_selection(cfg)
    _ssh(cfg, f"mkdir -p {bench}/eval_cases/full {sel}/judge {sel}/results")


def sync_bench_to_ecs(cfg: dict) -> None:
    host = cfg["ecs"]["host"]
    bench = cfg["ecs"]["bench_path"]
    sel = _remote_selection(cfg)
    _ensure_remote_dirs(cfg)

    # 考卷：本地中文文件名 → ECS ASCII 文件名
    pairs = [
        (
            _BENCH / "eval_cases" / "full" / "单轮测试集.json",
            f"{bench}/eval_cases/full/singleturn_fixed50.json",
        ),
        (
            _BENCH / "eval_cases" / "full" / "多轮测试集.json",
            f"{bench}/eval_cases/full/multiturn_fixed50.json",
        ),
    ]
    for local, remote in pairs:
        if local.is_file():
            subprocess.check_call(
                ["scp", "-o", "BatchMode=yes", str(local), f"{host}:{remote}"]
            )

    # model_selection 脚本（ASCII 目录）
    for name in [
        "multiturn_metrics.py",
        "config.json",
    ]:
        src = _MODEL_SEL / name
        if src.is_file():
            subprocess.check_call(
                ["scp", "-o", "BatchMode=yes", str(src), f"{host}:{sel}/"]
            )
    judge_local = _MODEL_SEL / "judge" / "multiturn_judge.json"
    if judge_local.is_file():
        subprocess.check_call(
            ["scp", "-o", "BatchMode=yes", str(judge_local), f"{host}:{sel}/judge/"]
        )

    for script in [
        "collect_openclaw_pred.py",
        "run_agent_eval.py",
        "load_cases.py",
        "intake_simulator.py",
        "simulate_user_reply.py",
        "rubric_engine.py",
        "rubric_context.py",
        "task_metrics.py",
        "process_metrics.py",
        "score_dimensions.py",
        "tool_schema_validate.py",
        "rubric.json",
        "score_dimensions.json",
    ]:
        src = _BENCH / script
        if src.is_file():
            subprocess.check_call(
                ["scp", "-o", "BatchMode=yes", str(src), f"{host}:{bench}/"]
            )


def switch_model(model_alias: str) -> None:
    if not _SWITCH.is_file():
        raise FileNotFoundError(_SWITCH)
    subprocess.check_call(
        [sys.executable, str(_SWITCH), model_alias, "--restart-gateway"],
        cwd=str(_ROOT),
    )


def remote_collect_and_eval(
    cfg: dict,
    *,
    model_alias: str,
    dataset: str,
    run_id: str,
    only: str = "",
    resume: bool = False,
    dry_run: bool = False,
) -> dict:
    remote_bench = cfg["ecs"]["bench_path"]
    sel = _remote_selection(cfg)
    cases_rel = _cases_remote(cfg, dataset)
    out_dir = f"{sel}/results/{run_id}/{model_alias}"
    pred_name = f"pred_{dataset}.jsonl"
    eval_name = f"eval_{dataset}.json"

    if dry_run:
        return {"dry_run": True, "model": model_alias, "dataset": dataset, "out_dir": out_dir}

    sync_bench_to_ecs(cfg)
    switch_model(model_alias)

    ds = cfg["datasets"][dataset]
    sim_mode = ds.get("sim_mode", "auto")
    max_turns = ds.get("max_turns", 5)
    only_flag = f" --only {only}" if only else ""
    resume_flag = " --resume" if resume else ""
    eval_only = only_flag if only.strip() and not resume else ""
    remote_cmd = (
        f"mkdir -p {out_dir} && cd {remote_bench} && "
        f"python3 collect_openclaw_pred.py --cases {cases_rel} "
        f"-o {out_dir}/{pred_name} --audit-out {out_dir}/simulation_audit.jsonl "
        f"--max-turns {max_turns} --sim-mode {sim_mode}{only_flag}{resume_flag} && "
        f"python3 run_agent_eval.py --cases {cases_rel} --pred {out_dir}/{pred_name} "
        f"-o {out_dir}/{eval_name}{eval_only}; "
        f"test -f {out_dir}/{eval_name} && test -f {out_dir}/{pred_name}"
    )
    proc = _ssh(cfg, remote_cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"remote collect failed:\n{proc.stdout}\n{proc.stderr}")

    local_out = _MODEL_SEL / "results" / run_id / model_alias
    local_out.mkdir(parents=True, exist_ok=True)
    host = cfg["ecs"]["host"]
    for fname in [pred_name, eval_name, "simulation_audit.jsonl"]:
        remote_file = f"{out_dir}/{fname}"
        try:
            subprocess.check_call(
                ["scp", "-o", "BatchMode=yes", f"{host}:{remote_file}", str(local_out / fname)]
            )
        except subprocess.CalledProcessError:
            if fname == "simulation_audit.jsonl":
                continue
            raise

    if dataset == "multiturn":
        judge_path = cfg["datasets"]["multiturn"]["judge_path"]
        mt_script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, "{sel}")
from multiturn_metrics import load_judges, evaluate_multiturn_all
out_dir = Path("{out_dir}")
judges = load_judges(Path("{remote_bench}/{judge_path}"))
preds = {{json.loads(l)["case_id"]: json.loads(l) for l in out_dir.joinpath("{pred_name}").read_text(encoding="utf-8").splitlines() if l.strip()}}
ev = json.loads(out_dir.joinpath("{eval_name}").read_text(encoding="utf-8"))
rb = {{r["case_id"]: r for r in ev.get("results", [])}}
mt = evaluate_multiturn_all(judges, preds, rb)
out_dir.joinpath("multiturn_metrics.json").write_text(json.dumps(mt, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok")
"""
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(mt_script)
            tmp = f.name
        try:
            subprocess.check_call(
                ["scp", "-o", "BatchMode=yes", tmp, f"{host}:/tmp/_mt_eval.py"]
            )
            proc2 = _ssh(cfg, f"python3 /tmp/_mt_eval.py")
            if proc2.returncode == 0:
                subprocess.check_call(
                    [
                        "scp",
                        "-o",
                        "BatchMode=yes",
                        f"{host}:{out_dir}/multiturn_metrics.json",
                        str(local_out / "multiturn_metrics.json"),
                    ]
                )
        finally:
            Path(tmp).unlink(missing_ok=True)

    summary = json.loads((local_out / eval_name).read_text(encoding="utf-8"))
    return {
        "model": model_alias,
        "dataset": dataset,
        "local_dir": str(local_out),
        "task_success_rate_pct": summary.get("task_success_rate_pct"),
        "passed": summary.get("passed"),
        "total": summary.get("cases"),
    }
