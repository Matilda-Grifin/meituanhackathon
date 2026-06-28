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
from lifecare.harness.poi_whitelist import (
    apply_poi_images,
    apply_poi_whitelist,
    build_whitelist_from_tools,
    extract_pois_from_tool_result,
    normalize_poi_name,
)
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


def test_freetext_intake_allows_search() -> None:
    set_active_session("test-freetext")
    on_user_message("test-freetext", "帮我安排杭州半日出游")
    st = on_user_message("test-freetext", "我们3个人，地铁出行，不忌口，下午出发", intake_skipped=True)
    assert st["slots"]["ready"] is True
    assert st["slots"]["intake_consumed"] is True
    assert st["slots"]["intake_mode"] == "skipped_freetext"
    assert st["stage"] == "planning"
    blocked = check_pre_tool("lifecare_search_places", {"keywords": "博物馆", "city": "杭州"})
    assert blocked is None
    print("ok test_freetext_intake_allows_search")


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


def _img_whitelist():
    return build_whitelist_from_tools(
        [
            {
                "tool": "lifecare_search_places",
                "ok": True,
                "pois": [
                    {
                        "id": "B0FFGAMP01",
                        "name": "浙江省博物馆",
                        "amap_place_url": "https://www.amap.com/place/B0FFGAMP01",
                        "photo_urls": ["http://store.is.autonavi.com/museum1.jpg"],
                    },
                    {
                        "id": "B0FFGAMP02",
                        "name": "外婆家(湖滨店)",
                        "amap_place_url": "https://www.amap.com/place/B0FFGAMP02",
                        "photo_urls": ["http://store.is.autonavi.com/food2.jpg"],
                    },
                ],
            }
        ]
    )


def test_poi_images_backfill_when_missing() -> None:
    wl = _img_whitelist()
    plan = (
        "## 📋 行程速览\n\n| 时段 | 做什么 |\n|---|---|\n| 10:00 | 看展 |\n\n"
        "### 10:00 浙江省博物馆\n\n停留约 2 小时。[浙江省博物馆 →](https://www.amap.com/place/B0FFGAMP01)\n\n"
        "### 12:00 外婆家(湖滨店)\n\n本帮菜。[外婆家 →](https://www.amap.com/place/B0FFGAMP02)\n"
    )
    out, added = apply_poi_images(plan, wl)
    assert added, "缺图方案应被补图"
    assert "![浙江省博物馆](http://store.is.autonavi.com/museum1.jpg)" in out
    print("ok test_poi_images_backfill_when_missing")


def test_poi_images_skip_when_already_has_image() -> None:
    wl = _img_whitelist()
    plan = "### 10:00 浙江省博物馆\n\n![已有](http://x/a.jpg)\n[浙博 →](https://www.amap.com/place/B0FFGAMP01)\n"
    out, added = apply_poi_images(plan, wl)
    assert not added, "已有图的方案不应被改动"
    assert out == plan
    print("ok test_poi_images_skip_when_already_has_image")


def test_poi_images_cap() -> None:
    pois = [
        {
            "id": f"P{i:02d}",
            "name": f"测试地点{i}",
            "amap_place_url": f"https://www.amap.com/place/P{i:02d}",
            "photo_urls": [f"http://x/p{i}.jpg"],
        }
        for i in range(8)
    ]
    wl = build_whitelist_from_tools([{"tool": "lifecare_search_places", "ok": True, "pois": pois}])
    plan = "\n\n".join(f"### {10 + i}:00 测试地点{i}" for i in range(8)) + "\n"
    out, added = apply_poi_images(plan, wl, max_images=4)
    assert len(added) == 4, f"应受 max_images 限制，实际 {len(added)}"
    print("ok test_poi_images_cap")


def test_extract_photo_urls_from_tool_result() -> None:
    raw = json.dumps(
        {
            "ok": True,
            "pois": [
                {
                    "id": "B0XYZ",
                    "name": "某馆",
                    "amap_place_url": "https://www.amap.com/place/B0XYZ",
                    "photo_urls": ["http://store.is.autonavi.com/a.jpg", "not-a-url"],
                }
            ],
        }
    )
    entries = extract_pois_from_tool_result(raw)
    assert entries and entries[0].photo_urls == ["http://store.is.autonavi.com/a.jpg"]
    print("ok test_extract_photo_urls_from_tool_result")


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


def test_light_weather_fail_open_on_mixed_message() -> None:
    """008：看展/公园/创意菜+查天气 的混合诉求不应被判 light_weather 拦死搜点。"""
    from lifecare.harness.tool_validate import validate_tool_arguments

    mixed = ("就我自己。想看展，然后去湖边或公园走走。预算不是问题。"
             "吃饭要创意菜，我不吃甜的，人均两三百都行，环境好最重要。"
             "帮我查下那天天气，路线别太折腾，我想慢慢逛。")
    assert detect_light_weather(mixed, mixed) is False, "混合诉求不应判纯天气"
    # 纯天气仍判 light_weather（回归）
    assert detect_light_weather("杭州明天冷吗", "杭州明天冷吗") is True
    assert detect_light_weather("杭州未来一周天气怎么样", "杭州未来一周天气怎么样") is True

    # 端到端：口语跳过 intake 后该消息应进 planning 且放行搜点
    set_active_session("test-lw-mixed")
    on_user_message("test-lw-mixed", mixed, intake_skipped=True)
    blocked = check_pre_tool("lifecare_search_places", {"keywords": "美术馆 展览", "city": "杭州"})
    assert blocked is None, f"混合诉求应放行搜点，却被拦：{blocked}"

    # A1：get_weather(city=null) 不再被 schema 拦
    v = validate_tool_arguments("lifecare_get_weather", {"city": None, "forecast_days": 7})
    assert v["valid"] is True, f"get_weather(city=null) 应通过校验：{v}"
    print("ok test_light_weather_fail_open_on_mixed_message")


def test_plan_route_cuqps_does_not_poison_search() -> None:
    """单次 plan_route 限流不应让整段会话 search_degraded，且后续成功应自愈。"""
    from lifecare.harness.session_state import load_state

    set_active_session("test-cuqps")
    on_user_message("test-cuqps", "帮我安排杭州一日游")
    on_user_message("test-cuqps", "2个人，地铁，不忌口，上午出发", intake_skipped=True)
    ok_search = json.dumps({"ok": True, "pois": [
        {"id": "B0X1", "name": "浙江省博物馆", "type": "风景名胜",
         "amap_place_url": "https://www.amap.com/place/B0X1",
         "photo_urls": ["http://store.is.autonavi.com/a.jpg"]},
    ]}, ensure_ascii=False)
    record_tool_call("test-cuqps", "lifecare_search_places", {"keywords": "博物馆", "city": "杭州"}, ok_search)
    # plan_route 撞高德限流
    record_tool_call("test-cuqps", "lifecare_plan_route", {"o": "1", "d": "2"},
                     json.dumps({"ok": False, "error": "CUQPS_HAS_EXCEEDED_THE_LIMIT"}))
    st = load_state("test-cuqps")
    assert st["search_degraded"] is False, "plan_route 限流不应污染 search_degraded"
    # plan_route 恢复成功 → tools_degraded 自愈
    record_tool_call("test-cuqps", "lifecare_plan_route", {"o": "3", "d": "4"},
                     json.dumps({"ok": True, "distance_m": 1000, "duration_s": 600}))
    st = load_state("test-cuqps")
    assert st["tools_degraded"] is False, "后续成功应清除 tools_degraded"
    print("ok test_plan_route_cuqps_does_not_poison_search")


def test_search_degraded_recovers_on_success() -> None:
    set_active_session("test-recover")
    on_user_message("test-recover", "帮我安排杭州一日游")
    on_user_message("test-recover", "2个人，地铁，不忌口，上午出发", intake_skipped=True)
    record_tool_call("test-recover", "lifecare_search_places", {"keywords": "x", "city": "杭州"},
                     json.dumps({"ok": False, "error": "CUQPS_HAS_EXCEEDED_THE_LIMIT"}))
    from lifecare.harness.session_state import load_state
    assert load_state("test-recover")["search_degraded"] is True
    record_tool_call("test-recover", "lifecare_search_places", {"keywords": "y", "city": "杭州"},
                     json.dumps({"ok": True, "pois": [{"id": "B0Y", "name": "某馆",
                      "amap_place_url": "https://www.amap.com/place/B0Y"}]}))
    assert load_state("test-recover")["search_degraded"] is False
    print("ok test_search_degraded_recovers_on_success")


def test_tool_budget_is_per_turn() -> None:
    """搜索预算按轮计：第 1 轮用满 4 次 search，第 2 轮（新用户消息）应重新放行。"""
    from lifecare.harness.pre_tool import check_pre_tool
    from lifecare.harness.session_state import load_state

    set_active_session("test-budget-turn")
    on_user_message("test-budget-turn", "帮我安排杭州一日游")
    on_user_message("test-budget-turn", "2个人，地铁，不忌口，上午出发", intake_skipped=True)
    okres = json.dumps({"ok": True, "pois": [{"id": "B0A", "name": "某馆",
                       "amap_place_url": "https://www.amap.com/place/B0A"}]}, ensure_ascii=False)
    for _ in range(4):
        record_tool_call("test-budget-turn", "lifecare_search_places",
                         {"keywords": str(_), "city": "杭州"}, okres)
    # 第 1 轮第 5 次 search 应被预算拦截
    blocked = check_pre_tool("lifecare_search_places", {"keywords": "x", "city": "杭州"})
    assert blocked is not None and "预算" in blocked, "同轮第 5 次 search 应被预算拦截"
    # 用户追问开启第 2 轮 → 预算刷新，应放行
    on_user_message("test-budget-turn", "换成看花卉市场，中午吃云南菜")
    allowed = check_pre_tool("lifecare_search_places", {"keywords": "花卉市场", "city": "杭州"})
    assert allowed is None, f"新一轮 search 应放行，却被拦：{allowed}"
    st = load_state("test-budget-turn")
    assert st["search_degraded"] is False
    print("ok test_tool_budget_is_per_turn")


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
    test_freetext_intake_allows_search()
    test_light_weather_allows_weather_blocks_search()
    test_chitchat_blocks_tools()
    test_output_repair_budget()
    test_checklist_patches_missing_budget()
    test_poi_whitelist_replace()
    test_poi_images_backfill_when_missing()
    test_poi_images_skip_when_already_has_image()
    test_poi_images_cap()
    test_extract_photo_urls_from_tool_result()
    test_poi_name_normalize()
    test_skip_intake_bubble()
    test_intent_detection()
    test_light_weather_fail_open_on_mixed_message()
    test_plan_route_cuqps_does_not_poison_search()
    test_search_degraded_recovers_on_success()
    test_tool_budget_is_per_turn()
    test_retry_fuse_blocks_same_params()
    print("ALL PASS")
