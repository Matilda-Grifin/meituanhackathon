#!/usr/bin/env python3
"""Unit tests for vitabench_eval harness_bridge."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BENCH = Path(__file__).resolve().parent.parent
_REPO = _BENCH.parent
for p in (_BENCH, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

_tmp = tempfile.mkdtemp(prefix="v63_harness_bridge_")
os.environ["LIFECARE_HARNESS_STATE_DIR"] = _tmp
os.environ["LIFECARE_HARNESS_LOG"] = "0"

from vitabench_eval.harness_bridge import apply_harness_post_output, prepare_harness_turn  # noqa: E402
from lifecare.harness.session_state import on_user_message, record_tool_call, set_active_session  # noqa: E402


def test_prepare_and_post_output_plan() -> None:
    sk = "v63-test-bridge"
    set_active_session(sk)
    prepare_harness_turn(sk, "帮我规划杭州半日，2人")
    on_user_message(sk, "选择题答案：第1题选A；第2题选B；第3题选C")
    record_tool_call(
        sk,
        "lifecare_get_weather",
        {"city": "杭州"},
        '{"ok": true, "temperature": 20}',
    )
    record_tool_call(
        sk,
        "lifecare_search_places",
        {"keywords": "博物馆", "city": "杭州"},
        '{"ok": true, "pois": [{"id": "B001", "name": "浙江省博物馆", "amap_place_url": "https://www.amap.com/place/B001"}]}',
    )
    record_tool_call(
        sk,
        "lifecare_plan_route",
        {"origin": "a", "destination": "b"},
        '{"ok": true, "distance_km": 3, "duration_min": 12}',
    )
    raw = (
        "## 📋 行程速览\n\n| 时段 | 做什么 | 交通 |\n|---|---|---|\n"
        "| 10:00 | 文和友 | 打车约 3km / 12分钟 |\n\n"
        "## 💰 预算参考\n\n| 项目 | 费用 |\n|---|---|\n| 餐饮 | 200 |"
    )
    out = apply_harness_post_output(sk, raw)
    assert out.get("skipped") is False
    assert "文和友" not in out["text"] or "poi_whitelist" in (out.get("repairs_applied") or [])
    print("ok test_prepare_and_post_output_plan")


def test_skips_intake_questions() -> None:
    sk = "v63-test-intake"
    prepare_harness_turn(sk, "帮我规划")
    intake = "第1题：几人出行？\nA. 1人\nB. 2人"
    out = apply_harness_post_output(sk, intake)
    assert out.get("skipped") is True
    assert out["text"] == intake
    print("ok test_skips_intake_questions")


if __name__ == "__main__":
    test_prepare_and_post_output_plan()
    test_skips_intake_questions()
    print("all harness_bridge tests passed")
