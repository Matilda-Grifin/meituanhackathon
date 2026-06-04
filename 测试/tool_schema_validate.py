#!/usr/bin/env python3
"""校验 lifecare 工具调用参数（§6.2 Schema 合规）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_BENCH = Path(__file__).resolve().parent

_ROLE_SUFFIX = {
    "search_places": "lifecare_search_places",
    "get_weather": "lifecare_get_weather",
    "plan_route": "lifecare_plan_route",
}


def _load_schemas(path: Path | None = None) -> dict:
    p = path or _BENCH / "tool_schemas.json"
    return json.loads(p.read_text(encoding="utf-8"))


def normalize_tool_name(name: str) -> str | None:
    s = str(name or "").replace("lifecare__", "").replace("lifecare_", "")
    for short, full in _ROLE_SUFFIX.items():
        if short in s or s == full:
            return full
    return None


def _check_type(value: Any, kind: str) -> bool:
    if kind == "str_nonempty":
        return isinstance(value, str) and bool(value.strip())
    if kind == "str":
        return value is None or isinstance(value, str)
    if kind == "number":
        return isinstance(value, (int, float))
    if kind == "int_1_20":
        return isinstance(value, int) and 1 <= value <= 20
    if kind == "int_1_16":
        return isinstance(value, int) and 1 <= value <= 16
    return True


def validate_tool_arguments(tool_name: str, arguments: Any, schemas: dict | None = None) -> dict[str, Any]:
    """返回 {valid, errors[], schema_key}。"""
    schemas = schemas or _load_schemas()
    key = normalize_tool_name(tool_name)
    if not key:
        return {"valid": None, "errors": ["unknown_tool"], "schema_key": None}

    spec = (schemas.get("tools") or {}).get(key)
    if not spec:
        return {"valid": None, "errors": ["no_schema"], "schema_key": key}

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return {"valid": False, "errors": ["arguments_not_json"], "schema_key": key}
    if not isinstance(arguments, dict):
        return {"valid": False, "errors": ["arguments_not_object"], "schema_key": key}

    errors: list[str] = []
    for req in spec.get("required") or []:
        if req not in arguments:
            errors.append(f"missing:{req}")
    for opt in spec.get("optional") or []:
        if opt in arguments and arguments[opt] is not None:
            kind = (spec.get("types") or {}).get(opt)
            if kind and not _check_type(arguments[opt], kind):
                errors.append(f"type:{opt}")
    for req in spec.get("required") or []:
        kind = (spec.get("types") or {}).get(req)
        if kind and req in arguments and not _check_type(arguments[req], kind):
            errors.append(f"type:{req}")

    at_least = spec.get("at_least_one_of") or []
    if at_least and not any(arguments.get(k) not in (None, "") for k in at_least):
        errors.append(f"need_one_of:{at_least}")

    return {"valid": len(errors) == 0, "errors": errors, "schema_key": key}


def validate_pred_tool_calls(pred: dict, schemas: dict | None = None) -> dict[str, Any]:
    """对 pred 中 tool_calls_detail 或 turns[].tool_calls 做批量校验。"""
    schemas = schemas or _load_schemas()
    calls: list[dict] = list(pred.get("tool_calls_detail") or [])
    if not calls:
        for turn in pred.get("turns") or []:
            for tc in turn.get("tool_calls") or []:
                if isinstance(tc, dict):
                    calls.append(tc)

    if not calls:
        return {
            "schema_compliance_rate": None,
            "valid_count": 0,
            "total_with_args": 0,
            "details": [],
            "note": "no_tool_calls_with_arguments",
        }

    details = []
    valid_n = 0
    for tc in calls:
        name = tc.get("name") or tc.get("tool") or ""
        args = tc.get("arguments") or tc.get("args")
        if args is None:
            details.append({"tool": name, "valid": None, "skipped": "no_arguments"})
            continue
        r = validate_tool_arguments(name, args, schemas)
        if r.get("valid"):
            valid_n += 1
        details.append({"tool": name, **r})

    total = sum(1 for d in details if d.get("valid") is not None)
    rate = round(100.0 * valid_n / total, 1) if total else None
    return {
        "schema_compliance_rate": rate,
        "valid_count": valid_n,
        "total_with_args": total,
        "details": details,
    }
