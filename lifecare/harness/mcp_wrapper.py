from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

from lifecare.harness.post_tool import record_post_tool
from lifecare.harness.pre_tool import check_pre_tool

T = TypeVar("T")


def run_with_harness(
    tool_name: str,
    arguments: dict[str, Any],
    execute: Callable[[], T],
) -> T | str:
    """
    Pre-Tool 校验 → 执行 → Post-Tool 记录。
    拦截时返回 JSON 字符串（与 MCP 其它错误风格一致）。
    """
    blocked = check_pre_tool(tool_name, arguments)
    if blocked:
        return blocked
    result = execute()
    if isinstance(result, str):
        record_post_tool(tool_name, arguments, result)
    else:
        record_post_tool(tool_name, arguments, json.dumps(result, ensure_ascii=False))
    return result
