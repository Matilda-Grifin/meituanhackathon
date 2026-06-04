#!/usr/bin/env python3
"""等待 run 结束后归档到待修复/结果（用于已启动、未带自动归档的批次）。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_MODEL_SEL = Path(__file__).resolve().parent
RUN_ID = "20260602-full"
MODEL = "doubao"
POLL_S = 120
MAX_WAIT_S = 8 * 3600


def _done() -> bool:
    manifest = _MODEL_SEL / "results" / RUN_ID / "manifest.json"
    if not manifest.is_file():
        return False
    m = json.loads(manifest.read_text(encoding="utf-8"))
    md = (m.get("models") or {}).get(MODEL) or {}
    for ds in ("singleturn", "multiturn"):
        if ds not in md or md[ds].get("error"):
            return False
    return True


def main() -> int:
    waited = 0
    while waited < MAX_WAIT_S:
        if _done():
            from archive_to_report_data import archive

            out = archive(RUN_ID, [MODEL])
            print(json.dumps({"status": "archived", **out}, ensure_ascii=False))
            prog = _MODEL_SEL.parent.parent.parent / "待修复" / "模型选型评测" / "结果" / "runs" / RUN_ID
            (prog / "进行中.json").unlink(missing_ok=True)
            return 0
        time.sleep(POLL_S)
        waited += POLL_S
    print(json.dumps({"status": "timeout"}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
