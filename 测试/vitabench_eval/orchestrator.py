"""VitaBench-style orchestrator (OpenClaw adaptation: Agent turn includes MCP; Env via log merge)."""
from __future__ import annotations

import uuid
from typing import Any

from vitabench_eval.agent_bridge import format_environment_block, run_agent_turn
from vitabench_eval.env_runner import McpLogTracker, count_mcp_errors, entries_to_tool_messages
from vitabench_eval.harness_bridge import apply_harness_post_output, prepare_harness_turn
from vitabench_eval.user_simulator import STOP, UserSimulator

EARLY_ZERO = frozenset({"max_steps", "too_many_errors", "agent_error", "invalid_agent_message"})


def run_simulation(
    task: dict,
    *,
    session_prefix: str = "v63",
    max_steps: int = 100,
    max_errors: int = 10,
    agent_timeout_s: int = 180,
    skip_judge: bool = False,
    judge_model: str = "judge",
    user_model: str = "user",
    user_temperature: float | None = None,
    judge_temperature: float | None = None,
) -> dict[str, Any]:
    task_id = task.get("id") or "unknown"
    session_id = f"{session_prefix}-{task_id}-{uuid.uuid4().hex[:8]}"
    env_block = format_environment_block(task.get("environment") or {})
    user_sim = UserSimulator(
        task,
        model=user_model,
        temperature=user_temperature if user_temperature is not None else 0.6,
    )
    mcp_tracker = McpLogTracker()
    trajectory: list[dict] = []
    harness_turns: list[dict] = []
    termination = "unknown"
    num_errors = 0
    step = 0
    first_ttft = None

    user_msg = user_sim.first_message()
    trajectory.append({"role": "user", "content": user_msg, "turn": 1})
    if UserSimulator.is_stop(user_msg):
        termination = "user_stop"
        step = 0

    while step < max_steps and termination == "unknown":
        step += 1
        if UserSimulator.is_empty(user_msg):
            user_msg = STOP
            trajectory.append(
                {
                    "role": "user",
                    "content": user_msg,
                    "turn": step,
                    "empty_user_replaced": True,
                }
            )
            termination = "user_stop"
            break

        inject = env_block if step == 1 else None
        prepare_harness_turn(session_id, user_msg)
        agent_out = run_agent_turn(
            user_msg,
            session_id=session_id,
            timeout_s=agent_timeout_s,
            inject_env=inject,
        )

        if agent_out.get("error"):
            num_errors += 1
            trajectory.append(
                {
                    "role": "assistant",
                    "content": f"[agent_error] {agent_out['error']}",
                    "turn": step,
                    "error": agent_out["error"],
                }
            )
            termination = "agent_error"
            break

        asst_text_raw = agent_out.get("assistant_text") or ""
        has_tools = bool(agent_out.get("tools") or agent_out.get("tool_calls"))
        if not asst_text_raw.strip() and not has_tools:
            num_errors += 1
            termination = "invalid_agent_message"
            trajectory.append(
                {
                    "role": "assistant",
                    "content": "[invalid_agent_message] empty reply",
                    "turn": step,
                }
            )
            break

        if first_ttft is None:
            first_ttft = agent_out.get("time_to_first_assistant_text_ms") or agent_out.get(
                "time_to_first_progress_ms"
            )

        mcp_entries = mcp_tracker.drain_new_entries()
        harness = apply_harness_post_output(session_id, asst_text_raw)
        asst_text = harness.get("text") or asst_text_raw
        harness_meta = {
            "skipped": harness.get("skipped"),
            "repairs_applied": harness.get("repairs_applied") or [],
            "checklist_missing": harness.get("checklist_missing") or [],
            "poi_audit": harness.get("poi_audit") or {},
        }
        harness_turns.append({"turn": step, **harness_meta})

        trajectory.append(
            {
                "role": "assistant",
                "content": asst_text,
                "turn": step,
                "tools": agent_out.get("tools") or [],
                "tool_calls": agent_out.get("tool_calls") or [],
                "time_to_first_assistant_text_ms": agent_out.get("time_to_first_assistant_text_ms"),
                "duration_ms": agent_out.get("duration_ms"),
                "harness": harness_meta,
                "assistant_text_raw": asst_text_raw if asst_text_raw != asst_text else None,
            }
        )

        # Env step: merge MCP JSONL tool results for judge visibility
        tool_msgs = entries_to_tool_messages(mcp_entries)
        for tm in tool_msgs:
            trajectory.append({**tm, "turn": step})
        mcp_errs = count_mcp_errors(mcp_entries)
        num_errors += mcp_errs

        if STOP in asst_text:
            termination = "agent_stop"
            break
        if UserSimulator.is_stop(user_msg):
            termination = "user_stop"
            break
        if num_errors >= max_errors:
            termination = "too_many_errors"
            break

        user_msg = user_sim.respond(asst_text)
        if UserSimulator.is_empty(user_msg):
            user_msg = STOP
        trajectory.append({"role": "user", "content": user_msg, "turn": step + 1})

        if UserSimulator.is_stop(user_msg):
            termination = "user_stop"
            break
    else:
        if termination == "unknown":
            termination = "max_steps"

    reward_info: dict[str, Any]
    if termination in EARLY_ZERO:
        reward_info = {"reward": 0.0, "reason": termination}
    elif skip_judge:
        reward_info = {"reward": 0.0, "skipped": True, "reason": "dry_run_eval"}
    else:
        from vitabench_eval.trajectory_evaluator import evaluate_trajectory

        jtemp = judge_temperature if judge_temperature is not None else 0.1
        reward_info = evaluate_trajectory(task, trajectory, model=judge_model, temperature=jtemp)

    from vitabench_eval.metrics import score_first_response

    fr = score_first_response(trajectory, first_ttft)
    return {
        "task_id": task_id,
        "session_id": session_id,
        "termination": termination,
        "steps": step,
        "num_errors": num_errors,
        "max_steps": max_steps,
        "max_errors": max_errors,
        "trajectory": trajectory,
        "harness_summary": {
            "turns": harness_turns,
            "repairs_total": sum(len(t.get("repairs_applied") or []) for t in harness_turns),
            "checklist_miss_total": sum(len(t.get("checklist_missing") or []) for t in harness_turns),
            "poi_replacements_total": sum(
                len((t.get("poi_audit") or {}).get("replacements") or []) for t in harness_turns
            ),
        },
        "reward_info": reward_info,
        "first_response": fr,
    }
