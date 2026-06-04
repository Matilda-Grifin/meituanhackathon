#!/usr/bin/env python3
"""本机打印意图启发式结果（不调高德、不调模型）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BENCH = Path(__file__).resolve().parent
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

from intent_heuristic import classify_intent_heuristic

SAMPLES = [
    "今天下午是空的，想和老婆孩子/朋友出去玩几个小时，别离家太远，帮我安排一下。",
    "家庭场景：孩子5岁，老婆最近在减肥",
    "朋友场景：总共有4个人，2个男生2个女生",
    "下午在杭州带娃逛博物馆，别太远",
]


def main() -> None:
    out = []
    for s in SAMPLES:
        out.append({"user_text": s, "heuristic": classify_intent_heuristic(s)})
    text = json.dumps(out, ensure_ascii=False, indent=2)
    out_path = _BENCH / "results" / "intent_smoke_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
