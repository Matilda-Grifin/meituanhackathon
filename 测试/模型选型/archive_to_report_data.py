#!/usr/bin/env python3
"""
把一次 run_id 的选型结果同步到「待修复/模型选型评测/结果」报告数据仓。

用法：
  python 模型选型/archive_to_report_data.py --run-id 20260602-full
  python 模型选型/archive_to_report_data.py --run-id 20260602-full --models doubao
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

_MODEL_SEL = Path(__file__).resolve().parent
_BENCH = _MODEL_SEL.parent
_ARCHIVE_ROOT = _BENCH.parent.parent / "待修复" / "模型选型评测" / "结果"
_CONDITIONS = _ARCHIVE_ROOT / "测评条件锁定.json"


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _copy_file(src: Path, dst: Path) -> None:
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def archive(run_id: str, models: list[str] | None) -> dict:
    src_run = _MODEL_SEL / "results" / run_id
    if not src_run.is_dir():
        raise FileNotFoundError(f"missing run dir: {src_run}")

    dst_run = _ARCHIVE_ROOT / "runs" / run_id
    dst_run.mkdir(parents=True, exist_ok=True)

    for fname in ("manifest.json", "comparison.json", "report_summary.json", "report.html"):
        _copy_file(src_run / fname, dst_run / fname)

    figures_src = src_run / "figures"
    if figures_src.is_dir():
        _copy_tree(figures_src, dst_run / "figures")

    model_dirs = []
    for d in sorted(src_run.iterdir()):
        if not d.is_dir() or d.name in ("figures",):
            continue
        if not (d / "eval_singleturn.json").is_file() and not (d / "eval_multiturn.json").is_file():
            continue
        if models and d.name not in models:
            continue
        _copy_tree(d, dst_run / d.name)
        model_dirs.append(d.name)

    if _CONDITIONS.is_file():
        _copy_file(_CONDITIONS, dst_run / "测评条件锁定.json")

    cfg = json.loads((_MODEL_SEL / "config.json").read_text(encoding="utf-8"))
    index = {
        "batch_id": run_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "models_archived": model_dirs,
        "config_version": cfg.get("version"),
        "archive_from": str(src_run),
    }
    if (dst_run / "index.json").is_file():
        old = json.loads((dst_run / "index.json").read_text(encoding="utf-8"))
        merged = sorted(set(old.get("models_archived") or []) | set(model_dirs))
        index["models_archived"] = merged
    (dst_run / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    return {"archive_root": str(dst_run), "models": index["models_archived"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--models", default="", help="逗号分隔，默认归档 run 下全部模型目录")
    args = ap.parse_args()
    models = [x.strip() for x in args.models.split(",") if x.strip()] or None
    out = archive(args.run_id, models)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
