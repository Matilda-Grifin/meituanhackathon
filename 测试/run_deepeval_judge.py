#!/usr/bin/env python3
"""
可选：用 DeepEval 对「最终回复」做 LLM-as-Judge（需 API Key，无需 Confident AI 账号）。

安装：pip install -r benchmark/requirements-eval-optional.txt
环境：与 OpenClaw 相同，需能调裁判模型，例如 ARK_API_KEY 或 OPENAI_API_KEY。

本脚本只评文本质量，不跑网关。输入：JSONL，每行 case_id + assistant_text + criteria。

用法：
  python benchmark/run_deepeval_judge.py --input benchmark/sample_judge_input.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        from deepeval import assert_test
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams
    except ImportError:
        print("请先: pip install -r benchmark/requirements-eval-optional.txt", file=sys.stderr)
        return 2

    if not (os.environ.get("ARK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("需要 ARK_API_KEY 或 OPENAI_API_KEY 作为裁判模型", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    args = ap.parse_args()

    rows = []
    for line in args.input.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))

    metric = GEval(
        name="ItineraryQuality",
        criteria="回复是否可执行、是否满足用户约束、是否避免编造未给出的排队/人数/预订事实。",
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.6,
    )

    ok = 0
    for row in rows:
        case = LLMTestCase(
            input=row.get("user_text", ""),
            actual_output=row.get("assistant_text", ""),
        )
        try:
            assert_test(case, [metric])
            ok += 1
            print(f"PASS {row.get('case_id')}")
        except Exception as e:
            print(f"FAIL {row.get('case_id')}: {e}")
    print(f"deepeval judge: {ok}/{len(rows)} passed")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
