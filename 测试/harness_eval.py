#!/usr/bin/env python3
"""测评侧 Harness 校验：与线上共用 lifecare.harness。"""
from __future__ import annotations

from typing import Any

from lifecare.harness.post_output import should_apply_harness_output, validate_and_repair
from lifecare.harness.session_state import on_user_message


def evaluate_pred_harness(case: dict, pred: dict) -> dict[str, Any]:
    session_id = pred.get("session_id") or case.get("case_id") or "eval"
    for um in pred.get("user_messages") or [case.get("user_text", "")]:
        if um:
            on_user_message(str(session_id), str(um))

    assistant_text = str(pred.get("assistant_text") or "")
    if not assistant_text:
        turns = pred.get("turns") or []
        if turns:
            assistant_text = str(turns[-1].get("assistant_text") or "")

    if not assistant_text or not should_apply_harness_output(assistant_text):
        return {
            "harness_skipped": True,
            "harness_repairs": [],
            "harness_violations": [],
        }

    result = validate_and_repair(str(session_id), assistant_text, apply_repairs=False)
    return {
        "harness_skipped": False,
        "harness_repairs": result.get("repairs_applied") or [],
        "harness_violations": result.get("violations") or [],
        "harness_would_repair": bool(result.get("repairs_applied")),
    }
