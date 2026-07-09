#!/usr/bin/env python3
"""Harness：方案交付后任意追问均应允许 search_places（LLM 决定是否调用）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lifecare.harness.pre_tool import check_pre_tool
from lifecare.harness.session_state import load_state, on_user_message, save_state


def _bootstrap_plan_session(sk: str) -> None:
    on_user_message(sk, "我想去杭州玩，帮我安排一日游")
    on_user_message(sk, "选择题答案：全部用默认")
    state = load_state(sk)
    state["has_full_plan"] = True
    slots = dict(state.get("slots") or {})
    slots.update({"ready": True, "intake_submitted": True, "city": "杭州", "trip_days": 1})
    state["slots"] = slots
    save_state(state)


def test_followup_chip_allows_search() -> None:
    sk = "test-followup-search-allow"
    _bootstrap_plan_session(sk)

    for msg in ("路线再轻松点", "附近加一家咖啡", "预算再低一点", "为什么选这家？"):
        on_user_message(sk, msg)
        state = load_state(sk)
        assert state["stage"] == "followup_replan", f"{msg!r} -> {state['stage']}"
        blocked = check_pre_tool("lifecare_search_places", {"keywords": "咖啡", "city": "杭州"})
        assert blocked is None, f"{msg!r} search blocked: {blocked}"


if __name__ == "__main__":
    test_followup_chip_allows_search()
    print("ok: followup allows search for all chip messages")
