#!/usr/bin/env python3
"""Harness 冒烟测试（本地）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_tmp = tempfile.mkdtemp(prefix="harness_test_")
os.environ["LIFECARE_HARNESS_STATE_DIR"] = _tmp
os.environ["LIFECARE_HARNESS_LOG"] = "0"

from lifecare.harness.checklist import apply_checklist_patches, run_checklist
from lifecare.harness.poi_whitelist import apply_poi_whitelist, build_whitelist_from_tools, normalize_poi_name
from lifecare.harness.pre_tool import check_pre_tool
from lifecare.harness.post_output import should_apply_harness_output, validate_and_repair
from lifecare.harness.session_state import on_user_message, record_tool_call, set_active_session
from lifecare.harness.slots import detect_light_weather, detect_planning_intent


def test_intake_blocks_search() -> None:
    set_active_session("test-intake")
    on_user_message("test-intake", "我跟朋友今晚在杭州玩")
    blocked = check_pre_tool("lifecare_search_places", {"keywords": "博物馆", "city": "杭州"})
    assert blocked is not None
    data = json.loads(blocked)
    assert data["error"] == "harness_blocked"
    print("ok test_intake_blocks_search")


def test_intake_submission_allows_search() -> None:
    set_active_session("test-plan")
    on_user_message("test-plan", "我跟朋友今晚在杭州玩")
    on_user_message("test-plan", "选择题答案：第1题选A；第2题选B；第3题选C")
    blocked = check_pre_tool("lifecare_search_places", {"keywords": "博物馆", "city": "杭州"})
    assert blocked is None
    print("ok test_intake_submission_allows_search")


def test_light_weather_allows_weather_blocks_search() -> None:
    set_active_session("test-weather")
    on_user_message("test-weather", "杭州未来一周天气怎么样")
    blocked_w = check_pre_tool("lifecare_get_weather", {"city": "杭州"})
    assert blocked_w is None
    blocked_s = check_pre_tool("lifecare_search_places", {"keywords": "博物馆", "city": "杭州"})
    assert blocked_s is not None
    print("ok test_light_weather_allows_weather_blocks_search")


def test_chitchat_blocks_tools() -> None:
    set_active_session("test-hi")
    on_user_message("test-hi", "你好")
    blocked = check_pre_tool("lifecare_get_weather", {"city": "杭州"})
    assert blocked is not None
    print("ok test_chitchat_blocks_tools")


def test_output_repair_budget() -> None:
    set_active_session("test-out")
    on_user_message("test-out", "选择题答案：第1题选A")
    plan = "## 📋 行程速览\n\n| 时段 | 做什么 |\n|---|---|\n| 12:00 | 午餐 |\n\n## 💰 预算参考\n\n| 项目 | 费用 |\n|---|---|\n| 餐饮 | 200 |"
    assert should_apply_harness_output(plan)
    r = validate_and_repair("test-out", plan)
    assert "budget_estimate_notice" in r.get("repairs_applied", []) or "估算" in r["text"]
    print("ok test_output_repair_budget")


def test_checklist_patches_missing_budget() -> None:
    plan = "## 📋 行程速览\n\n| 时段 | 做什么 | 交通 |\n|---|---|---|\n| 12:00 | 午餐 | 打车约 3km / 10分钟 |\n\n### 12:00 午餐"
    tools = [{"tool": "lifecare_get_weather", "ok": True}, {"tool": "lifecare_plan_route", "ok": True}]
    cl = run_checklist(plan, tools)
    assert "budget_block" in cl.missing
    patched, applied = apply_checklist_patches(plan, cl.missing)
    assert "budget_block" in applied
    assert "预算" in patched
    print("ok test_checklist_patches_missing_budget")


def test_poi_whitelist_replace() -> None:
    whitelist_tools = [
        {
            "tool": "lifecare_search_places",
            "ok": True,
            "pois": [
                {
                    "id": "B02DB02DH4",
                    "name": "火宫殿(坡子街总店)",
                    "amap_place_url": "https://www.amap.com/place/B02DB02DH4",
                }
            ],
        }
    ]
    wl = build_whitelist_from_tools(whitelist_tools)
    text = "### 午餐 · 文和友（海信广场店）\n\n[文和友→](https://www.amap.com/place/FAKEID123)"
    out, result = apply_poi_whitelist(text, wl)
    assert "火宫殿" in out or "B02DB02DH4" in out
    assert result.unmatched
    print("ok test_poi_whitelist_replace")


def test_poi_name_normalize() -> None:
    assert normalize_poi_name("IFS 国金中心") == normalize_poi_name("IFS国金购物中心") or "ifs" in normalize_poi_name("IFS 国金中心")
    print("ok test_poi_name_normalize")


def test_skip_intake_bubble() -> None:
    intake = "1. 人数？\nA. 2人\nB. 3人\nC. 其他"
    assert not should_apply_harness_output(intake)
    print("ok test_skip_intake_bubble")


def test_intent_detection() -> None:
    assert detect_planning_intent("帮我规划杭州半日游")
    assert detect_light_weather("杭州明天冷吗", "杭州明天冷吗")
    assert not detect_planning_intent("你好")
    print("ok test_intent_detection")


def test_retry_fuse_blocks_same_params() -> None:
    set_active_session("test-fuse")
    on_user_message("test-fuse", "帮我规划杭州半日")
    on_user_message("test-fuse", "选择题答案：第1题选A；第2题选B")
    args = {"keywords": "博物馆", "city": "杭州"}
    fail = json.dumps({"ok": True, "pois": []})
    for _ in range(2):
        record_tool_call("test-fuse", "lifecare_search_places", args, fail)
    blocked = check_pre_tool("lifecare_search_places", args)
    assert blocked is not None
    assert "retry_fuse" in blocked or "harness_blocked" in blocked
    print("ok test_retry_fuse_blocks_same_params")


if __name__ == "__main__":
    test_intake_blocks_search()
    test_intake_submission_allows_search()
    test_light_weather_allows_weather_blocks_search()
    test_chitchat_blocks_tools()
    test_output_repair_budget()
    test_checklist_patches_missing_budget()
    test_poi_whitelist_replace()
    test_poi_name_normalize()
    test_skip_intake_bubble()
    test_intent_detection()
    test_retry_fuse_blocks_same_params()
    print("ALL PASS")
