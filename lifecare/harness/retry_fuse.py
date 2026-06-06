from __future__ import annotations

import hashlib
import json
from typing import Any


def _tool_fingerprint(tool: str, arguments: dict[str, Any] | None) -> str:
    kind = tool.replace("lifecare__", "").replace("lifecare_", "")
    args = arguments or {}
    if kind.endswith("search_places"):
        key = json.dumps(
            {"keywords": args.get("keywords"), "city": args.get("city"), "limit": args.get("limit")},
            sort_keys=True,
            ensure_ascii=False,
        )
    elif kind.endswith("plan_route"):
        key = json.dumps(
            {
                "o": (args.get("origin_lng"), args.get("origin_lat")),
                "d": (args.get("dest_lng"), args.get("dest_lat")),
            },
            sort_keys=True,
        )
    elif kind.endswith("get_weather"):
        key = json.dumps({"city": args.get("city")}, sort_keys=True, ensure_ascii=False)
    else:
        key = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    raw = f"{kind}|{key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _is_empty_or_failed(result: str) -> bool:
    if not result or not result.strip():
        return True
    try:
        data = json.loads(result) if result.strip().startswith("{") else {}
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("ok") is False or data.get("error"):
        return True
    if "search_places" in result or "pois" in data:
        pois = data.get("pois") or []
        if isinstance(pois, list) and len(pois) == 0:
            return True
    return False


def check_retry_fuse(
    tools_called: list[dict[str, Any]],
    tool: str,
    arguments: dict[str, Any] | None,
    *,
    max_same: int = 3,
) -> tuple[bool, str | None]:
    fp = _tool_fingerprint(tool, arguments)
    same = 0
    for tc in reversed(tools_called):
        if tc.get("fingerprint") != fp:
            break
        if tc.get("blocked"):
            same += 1
            continue
        if tc.get("empty_or_failed"):
            same += 1
        elif tc.get("ok") is False:
            same += 1
        else:
            break
    if same >= max_same - 1:
        return False, "retry_fuse_same_params"
    return True, None
