#!/usr/bin/env python3
"""
一键跑测评套件（零注册；OpenClaw 采集可选）。

  python benchmark/run_eval_suite.py
  python benchmark/run_eval_suite.py --quick          # MCP 只跑 3 条
  python benchmark/run_eval_suite.py --with-openclaw    # 尝试 openclaw 采 pred 再评 agent
  python benchmark/run_eval_suite.py --skip-mcp         # 无 AMAP_KEY 时

写出汇总：benchmark/results/eval_suite_latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BENCH = Path(__file__).resolve().parent
_PY = sys.executable


def _run(name: str, cmd: list[str], *, optional: bool = False) -> dict:
    print(f"\n=== {name} ===", flush=True)
    proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    if proc.stdout.strip():
        print(proc.stdout.strip()[-2000:])
    if proc.stderr.strip() and not ok:
        print(proc.stderr.strip()[-1500:], file=sys.stderr)
    if not ok and not optional:
        print(f"FAIL {name} exit={proc.returncode}", file=sys.stderr)
    return {
        "name": name,
        "ok": ok,
        "exit_code": proc.returncode,
        "optional": optional,
        "cmd": cmd,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="MCP 仅 hz_museum,hz_food_scenic,sh_coffee")
    ap.add_argument("--skip-mcp", action="store_true")
    ap.add_argument("--skip-agent", action="store_true")
    ap.add_argument("--with-openclaw", action="store_true", help="采集 live pred（需 openclaw+网关）")
    ap.add_argument("--with-deepeval", action="store_true", help="有 API Key 时跑 LLM judge")
    args = ap.parse_args()

    steps: list[dict] = []
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if not args.skip_mcp:
        mcp_cmd = [_PY, str(_BENCH / "run_mcp_benchmark.py"), "--out", str(_BENCH / "results")]
        if args.quick:
            mcp_cmd.extend(["--only", "hz_museum,hz_food_scenic,sh_coffee"])
        has_amap = bool(os.environ.get("AMAP_KEY") or os.environ.get("amap_key"))
        steps.append(_run("mcp_benchmark", mcp_cmd, optional=not has_amap))
    else:
        steps.append({"name": "mcp_benchmark", "ok": True, "skipped": True})

    pred_path = _BENCH / "results" / "agent_pred_live.jsonl"
    has_pred = pred_path.is_file()

    audit_path = _BENCH / "results" / "simulation_audit.jsonl"
    if args.with_openclaw:
        collect_cmd = [
            _PY,
            str(_BENCH / "collect_openclaw_pred.py"),
            "-o",
            str(pred_path),
            "--audit-out",
            str(audit_path),
        ]
        steps.append(_run("collect_openclaw_pred", collect_cmd, optional=True))

    if not args.skip_agent:
        if has_pred:
            steps.append(
                _run(
                    "agent_eval",
                    [_PY, str(_BENCH / "run_agent_eval.py"), "--pred", str(pred_path)],
                )
            )
            eval_cmd = [
                _PY,
                str(_BENCH / "run_evaluator.py"),
                "--pred",
                str(pred_path),
                "--audit",
                str(audit_path),
            ]
            if args.with_deepeval:
                eval_cmd.append("--with-deepeval")
            steps.append(_run("evaluator", eval_cmd, optional=False))
        else:
            steps.append(
                {
                    "name": "agent_eval",
                    "ok": False,
                    "skipped": True,
                    "reason": "no results/agent_pred_live.jsonl — run collect_openclaw_pred.py or --with-openclaw",
                }
            )
            steps.append(
                {
                    "name": "evaluator",
                    "ok": False,
                    "skipped": True,
                    "reason": "no pred",
                }
            )

    steps.append(
        _run("intent_smoke", [_PY, str(_BENCH / "run_intent_smoke.py")], optional=True)
    )

    if args.with_deepeval and (os.environ.get("ARK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        judge_in = _BENCH / "sample_judge_input.jsonl"
        if judge_in.is_file():
            steps.append(
                _run(
                    "deepeval_judge",
                    [_PY, str(_BENCH / "run_deepeval_judge.py"), "--input", str(judge_in)],
                    optional=True,
                )
            )
    elif args.with_deepeval:
        steps.append({"name": "deepeval_judge", "ok": False, "skipped": True, "reason": "no API key"})

    required = [s for s in steps if not s.get("optional") and not s.get("skipped")]
    passed = sum(1 for s in required if s.get("ok"))
    report = {
        "timestamp": ts,
        "passed_steps": passed,
        "total_required_steps": len(required),
        "all_ok": passed == len(required),
        "steps": steps,
        "pred_used": str(pred_path),
    }
    out = _BENCH / "results" / "eval_suite_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n=== 汇总 written {out} all_ok={report['all_ok']} ===")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
