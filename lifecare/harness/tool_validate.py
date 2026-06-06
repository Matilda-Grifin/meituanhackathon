from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lifecare.harness.policy_loader import tool_schemas_path


def _load_schemas() -> dict:
    return json.loads(tool_schemas_path().read_text(encoding="utf-8"))


def normalize_tool_name(name: str) -> str | None:
    s = str(name or "").replace("lifecare__", "").replace("lifecare_", "")
    mapping = {
        "search_places": "lifecare_search_places",
        "get_weather": "lifecare_get_weather",
        "plan_route": "lifecare_plan_route",
    }
    for short, full in mapping.items():
        if short in s or s == full:
            return full
    if s.startswith("lifecare_"):
        return s
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


def validate_tool_arguments(tool_name: str, arguments: Any) -> dict[str, Any]:
    schemas = _load_schemas()
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
    for field in list(spec.get("required") or []) + list(spec.get("optional") or []):
        if field in arguments and arguments[field] is not None:
            kind = (spec.get("types") or {}).get(field)
            if kind and not _check_type(arguments[field], kind):
                errors.append(f"type:{field}")

    at_least = spec.get("at_least_one_of") or []
    if at_least and not any(arguments.get(k) not in (None, "") for k in at_least):
        errors.append(f"need_one_of:{at_least}")

    return {"valid": len(errors) == 0, "errors": errors, "schema_key": key}
