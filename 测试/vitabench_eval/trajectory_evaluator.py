"""Sliding-window rubric judge (6.3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vitabench_eval.llm_client import chat_completion_with_usage, load_repo_env, merge_usage, parse_json_array
from vitabench_eval.prompt_loader import load_yaml_prompt

_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "sliding_window_eval_template.yaml"
WINDOW_SIZE = 10
OVERLAP = 2


def _init_rubric_states(criteria: dict) -> dict[str, dict]:
    states: dict[str, dict] = {}
    idx = 0
    seen: set[str] = set()
    for block in criteria.get("expected_states") or []:
        for rubric in block.get("state_rubrics") or []:
            if rubric in seen:
                continue
            seen.add(rubric)
            key = f"rubric_{idx}"
            states[key] = {
                "rubric": rubric,
                "justification": "Not evaluated yet",
                "meetExpectation": False,
            }
            idx += 1
    for rubric in criteria.get("overall_rubrics") or []:
        if rubric in seen:
            continue
        seen.add(rubric)
        key = f"rubric_{idx}"
        states[key] = {
            "rubric": rubric,
            "justification": "Not evaluated yet",
            "meetExpectation": False,
        }
        idx += 1
    return states


def _sliding_windows(messages: list[dict], window_size: int = WINDOW_SIZE, overlap: int = OVERLAP) -> list[list[dict]]:
    if len(messages) <= window_size:
        return [messages]
    step = window_size - overlap
    windows: list[list[dict]] = []
    i = 0
    while i < len(messages):
        w = messages[i : i + window_size]
        if w:
            windows.append(w)
        if i + window_size >= len(messages):
            break
        i += step
    return windows


def _format_window(messages: list[dict], window_start_idx: int = 0) -> str:
    lines = []
    for j, m in enumerate(messages):
        turn = window_start_idx + j + 1
        role = m.get("role", "?")
        content = (m.get("content") or "")[:6000]
        if role == "assistant":
            tools = m.get("tool_calls") or m.get("tools") or []
            if tools:
                content = f"{content} [tool_calls={tools}]"
        if role == "tool":
            name = m.get("name") or "tool"
            content = f"tool {name}: {content[:4000]}"
        lines.append(f"[{turn}] {role}: {content}")
    return "\n".join(lines)


def _format_rubrics(states: dict[str, dict]) -> str:
    rows = []
    for key, state in states.items():
        rows.append(
            {
                "rubric_idx": key,
                "rubric": state["rubric"],
                "justification": state["justification"],
                "meetExpectation": state["meetExpectation"],
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def evaluate_trajectory(
    task: dict,
    messages: list[dict],
    *,
    model: str = "judge",
    temperature: float = 0.1,
    session_id: str = "",
    batch: str = "",
) -> dict[str, Any]:
    load_repo_env()
    criteria = task.get("evaluation_criteria") or {}
    states = _init_rubric_states(criteria)
    if not states:
        return {"reward": 1.0, "rubric_states": {}, "windows": 0, "rubric_met": 0, "rubric_total": 0}

    template = load_yaml_prompt(_TEMPLATE_PATH)
    env = task.get("environment") or {}
    env_info = (
        f"system_time={env.get('time', '')}; "
        f"city={(env.get('user_historical_behaviors') or {}).get('常住地', '')}"
    )
    user_instruction = task.get("instructions") or ""

    windows = _sliding_windows(messages)
    step = WINDOW_SIZE - OVERLAP
    window_logs: list[dict] = []
    judge_usage: dict = {"input": 0, "output": 0, "total": 0, "reasoning": 0, "cacheRead": 0, "runs": 0}
    judge_model_id = ""

    for wi, window in enumerate(windows):
        start_idx = wi * step if len(messages) > WINDOW_SIZE else 0
        system_prompt = template.format(
            env_info=env_info,
            user_instruction=user_instruction,
            window_size=WINDOW_SIZE,
            overlap=OVERLAP,
            window_idx=wi + 1,
            total_windows=len(windows),
        )
        user_prompt = (
            "# Input\n<window_content>\n"
            f"{_format_window(window, start_idx)}\n"
            "</window_content>\n\n<current_rubrics>\n"
            f"{_format_rubrics(states)}\n"
            "</current_rubrics>"
        )
        out = chat_completion_with_usage(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=4096,
            timeout_s=180,
            usage_role="judge",
            session_id=session_id,
            task_id=str(task.get("id") or ""),
            batch=batch,
        )
        merge_usage(judge_usage, out.get("usage"), model=out.get("model") or "")
        if out.get("model"):
            judge_model_id = out["model"]
        judge_usage["runs"] = int(judge_usage.get("runs") or 0) + 1
        updates = parse_json_array(out.get("text") or "")
        for item in updates:
            key = item.get("rubric_idx")
            if key and key in states:
                states[key]["meetExpectation"] = bool(item.get("meetExpectation"))
                states[key]["justification"] = str(
                    item.get("justification") or states[key]["justification"]
                )
        window_logs.append({"window": wi + 1, "updates": len(updates)})

    total = len(states)
    met = sum(1 for s in states.values() if s["meetExpectation"])
    reward = met / total if total else 0.0
    return {
        "reward": reward,
        "full_success": reward >= 1.0,
        "rubric_states": states,
        "windows": len(windows),
        "window_logs": window_logs,
        "rubric_met": met,
        "rubric_total": total,
        "usage": {**judge_usage, "model": judge_model_id},
    }
