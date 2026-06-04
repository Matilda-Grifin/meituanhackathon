"""Validate 6.3 Task JSON structure."""
from __future__ import annotations

REQUIRED_TOP = ("id", "domain", "environment", "user_scenario", "instructions", "evaluation_criteria")


def validate_task(task: dict) -> list[str]:
    errors: list[str] = []
    for k in REQUIRED_TOP:
        if k not in task:
            errors.append(f"missing field: {k}")
    env = task.get("environment") or {}
    if not env.get("time"):
        errors.append("environment.time required")
    if not env.get("user_id"):
        errors.append("environment.user_id required")
    crit = task.get("evaluation_criteria") or {}
    states = crit.get("expected_states") or []
    rubrics = []
    for block in states:
        rubrics.extend(block.get("state_rubrics") or [])
    rubrics.extend(crit.get("overall_rubrics") or [])
    if not rubrics:
        errors.append("evaluation_criteria has no rubrics")
    return errors
