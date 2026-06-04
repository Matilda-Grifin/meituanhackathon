#!/usr/bin/env python3
"""
模型选型主入口：6 模型 × 单轮/多轮 50 条（默认在 ECS 跑）。

用法：
  python 模型选型/run_model_benchmark.py --self-check-only
  python 模型选型/run_model_benchmark.py --models doubao --datasets singleturn --only 6,11
  python 模型选型/run_model_benchmark.py --run-id 20260602-v1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_MODEL_SEL = Path(__file__).resolve().parent
_BENCH = _MODEL_SEL.parent
if str(_MODEL_SEL) not in sys.path:
    sys.path.insert(0, str(_MODEL_SEL))

from compare_models import build_comparison  # noqa: E402
from remote_ecs_collect import load_config, remote_collect_and_eval  # noqa: E402
from self_check import run_self_check  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="", help="结果目录名，默认 UTC 时间戳")
    ap.add_argument("--models", default="", help="逗号分隔 alias，默认 config 全部 6 个")
    ap.add_argument("--datasets", default="singleturn,multiturn", help="singleturn / multiturn")
    ap.add_argument("--only", default="", help="逗号分隔 case_id，冒烟用")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-check-only", action="store_true")
    ap.add_argument("--skip-self-check", action="store_true")
    ap.add_argument("--no-archive", action="store_true", help="不同步到待修复/模型选型评测/结果")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="采集时跳过 pred 文件里已有 case_id（断点续跑，需配合同一 run-id）",
    )
    args = ap.parse_args()

    cfg = load_config()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if not args.skip_self_check or args.self_check_only:
        report = run_self_check(cfg)
        report_path = _MODEL_SEL / "results" / "self_check_latest.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"self_check": report["ok"], "issues": report["issues"]}, ensure_ascii=False))
        if args.self_check_only:
            return 0 if report["ok"] else 1
        if not report["ok"]:
            print("self-check failed; fix issues or pass --skip-self-check", file=sys.stderr)
            return 1

    models = [m["alias"] for m in cfg["models"]]
    if args.models.strip():
        models = [x.strip() for x in args.models.split(",") if x.strip()]

    datasets = [x.strip() for x in args.datasets.split(",") if x.strip()]
    manifest = {"run_id": run_id, "models": {}, "started_at": datetime.now(timezone.utc).isoformat()}

    for alias in models:
        manifest["models"][alias] = {}
        for ds in datasets:
            print(f"\n=== {alias} / {ds} ===")
            try:
                summary = remote_collect_and_eval(
                    cfg,
                    model_alias=alias,
                    dataset=ds,
                    run_id=run_id,
                    only=args.only,
                    resume=args.resume,
                    dry_run=args.dry_run,
                )
                manifest["models"][alias][ds] = summary
            except Exception as e:
                manifest["models"][alias][ds] = {"error": str(e)}
                print(f"ERROR: {e}", file=sys.stderr)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    out_manifest = _MODEL_SEL / "results" / run_id / "manifest.json"
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run:
        comparison = build_comparison(_MODEL_SEL / "results" / run_id)
        comp_path = _MODEL_SEL / "results" / run_id / "comparison.json"
        comp_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from generate_report import generate_report  # noqa: E402

        report_summary = generate_report(_MODEL_SEL / "results" / run_id, cfg)
        payload = {
            "manifest": str(out_manifest),
            "comparison": str(comp_path),
            "report_html": str(_MODEL_SEL / "results" / run_id / "report.html"),
            "figures": len(report_summary.get("figures") or []),
        }
        if not args.no_archive:
            from archive_to_report_data import archive  # noqa: E402

            archived = archive(run_id, models)
            payload["report_data_archive"] = archived["archive_root"]
            payload["models_archived"] = archived["models"]
        print(json.dumps(payload, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
