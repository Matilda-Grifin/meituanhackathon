#!/usr/bin/env python3
"""6.3 batch benchmark wrapper (single or multi task)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parent.parent
_RUN = _BENCH / "vitabench_eval" / "run_benchmark.py"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", default="", help="single task id")
    ap.add_argument("--task-ids", default="", help="comma-separated ids")
    ap.add_argument("--model", default="qwen", help="agent model alias (ECS switch only)")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--dry-run-eval", action="store_true")
    args = ap.parse_args()

    ids: list[str] = []
    if args.task_id:
        ids = [args.task_id]
    elif args.task_ids:
        ids = [x.strip() for x in args.task_ids.split(",") if x.strip()]
    else:
        ids = ["T063_007"]

    out_dir = Path(args.out_dir) if args.out_dir else _BENCH / "vitabench_eval" / "results" / "batch"
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for tid in ids:
        out = out_dir / f"{tid}_run.json"
        cmd = [
            sys.executable,
            str(_RUN),
            "--task-id",
            tid,
            "--out",
            str(out),
        ]
        if args.dry_run_eval:
            cmd.append("--dry-run-eval")
        proc = subprocess.run(cmd, cwd=str(_BENCH))
        if proc.returncode != 0:
            summaries.append({"task_id": tid, "ok": False})
            continue
        data = json.loads(out.read_text(encoding="utf-8"))
        summaries.append(
            {
                "task_id": tid,
                "ok": True,
                "termination": data.get("termination"),
                "reward": (data.get("reward_info") or {}).get("reward"),
            }
        )
    manifest = out_dir / "batch_summary.json"
    manifest.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
