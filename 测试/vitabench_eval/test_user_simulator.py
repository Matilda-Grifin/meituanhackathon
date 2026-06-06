#!/usr/bin/env python3
"""Tests for user simulator empty-message handling."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_BENCH = Path(__file__).resolve().parent.parent
_REPO = _BENCH.parent
for p in (_BENCH, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from vitabench_eval.user_simulator import STOP, UserSimulator  # noqa: E402

_TASK = {
    "user_scenario": {"user_profile": {"name": "测试用户"}},
    "instructions": "测试指令",
}


def test_respond_retries_then_stop() -> None:
    sim = UserSimulator(_TASK, model="user", temperature=0.6)
    with patch("vitabench_eval.user_simulator.chat_completion", side_effect=["", "", STOP]):
        out = sim.respond("assistant reply")
    assert out == STOP
    assert sim.history[-1]["content"] == STOP
    print("ok test_respond_retries_then_stop")


def test_respond_recovers_on_retry() -> None:
    sim = UserSimulator(_TASK, model="user", temperature=0.6)
    with patch("vitabench_eval.user_simulator.chat_completion", side_effect=["", "继续问天气"]):
        out = sim.respond("assistant reply")
    assert out == "继续问天气"
    print("ok test_respond_recovers_on_retry")


def test_is_stop_treats_empty_as_stop() -> None:
    assert UserSimulator.is_stop("")
    assert UserSimulator.is_stop("   ")
    assert UserSimulator.is_stop(STOP)
    assert not UserSimulator.is_stop("还有问题")
    print("ok test_is_stop_treats_empty_as_stop")


def test_orchestrator_skips_agent_on_empty_user() -> None:
    from vitabench_eval.orchestrator import run_simulation

    task = {
        "id": "TEST_EMPTY_USER",
        "user_scenario": {"user_profile": {}},
        "instructions": "x",
        "environment": {},
        "evaluation_criteria": {"state_rubrics": [], "overall_rubrics": []},
    }
    with patch(
        "vitabench_eval.user_simulator.chat_completion",
        side_effect=["你好", "", "", STOP],
    ):
        with patch("vitabench_eval.orchestrator.run_agent_turn") as run_turn:
            run_turn.return_value = {"assistant_text": "收到，还有什么？"}
            with patch("vitabench_eval.orchestrator.apply_harness_post_output") as post:
                post.return_value = {
                    "text": "收到，还有什么？",
                    "skipped": True,
                    "repairs_applied": [],
                    "checklist_missing": [],
                    "poi_audit": {},
                }
                with patch("vitabench_eval.orchestrator.McpLogTracker") as Mcp:
                    Mcp.return_value.drain_new_entries.return_value = []
                    result = run_simulation(task, skip_judge=True, max_steps=5)
        assert run_turn.call_count == 1
        assert result["termination"] == "user_stop"
        assert result["steps"] == 1
        last_user = [m for m in result["trajectory"] if m["role"] == "user"][-1]
        assert last_user["content"] == STOP
    print("ok test_orchestrator_skips_agent_on_empty_user")


if __name__ == "__main__":
    test_respond_retries_then_stop()
    test_respond_recovers_on_retry()
    test_is_stop_treats_empty_as_stop()
    test_orchestrator_skips_agent_on_empty_user()
    print("all user_simulator tests passed")
