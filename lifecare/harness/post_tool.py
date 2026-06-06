from __future__ import annotations

from typing import Any

from lifecare.harness.session_state import get_session_key, record_tool_call


def record_post_tool(tool_name: str, arguments: dict[str, Any] | None, result: str) -> None:
    record_tool_call(get_session_key(), tool_name, arguments, result, blocked=False)
