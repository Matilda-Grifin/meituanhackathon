"""6.3 eval ↔ lifecare.harness bridge (parity with Web UI harnessClient)."""
from __future__ import annotations

from typing import Any

from lifecare.harness.post_output import should_apply_harness_output, validate_and_repair
from lifecare.harness.session_state import on_user_message, set_active_session


def prepare_harness_turn(session_key: str, user_message: str) -> None:
    """Mirror POST /api/harness/on-user-message before each agent turn."""
    sk = (session_key or "").strip()
    msg = (user_message or "").strip()
    if not sk:
        return
    set_active_session(sk)
    if msg and not msg.startswith("[仿真环境") and not msg.startswith("[位置上下文]"):
        on_user_message(sk, msg)


def apply_harness_post_output(session_key: str, assistant_text: str) -> dict[str, Any]:
    """
    Mirror POST /api/harness/validate-and-repair after assistant output.
    Returns repaired text for trajectory / user simulator (user-visible final).
    """
    sk = (session_key or "").strip()
    text = assistant_text or ""
    if not sk or not text.strip():
        return {
            "text": text,
            "skipped": True,
            "repairs_applied": [],
            "checklist_missing": [],
            "poi_audit": {},
            "violations": [],
        }
    if not should_apply_harness_output(text):
        return {
            "text": text,
            "skipped": True,
            "repairs_applied": [],
            "checklist_missing": [],
            "poi_audit": {},
            "violations": [],
        }
    result = validate_and_repair(sk, text, apply_repairs=True)
    return {
        "text": result.get("text") or text,
        "skipped": bool(result.get("skipped")),
        "repairs_applied": list(result.get("repairs_applied") or []),
        "checklist_missing": list(result.get("checklist_missing") or []),
        "poi_audit": dict(result.get("poi_audit") or {}),
        "violations": list(result.get("violations") or []),
    }
