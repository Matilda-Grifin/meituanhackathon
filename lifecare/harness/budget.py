from __future__ import annotations

import re
from typing import Any


def max_plan_route(trip_days: int, anchors: int, *, half_day: bool = False) -> int:
    raw = trip_days * max(0, anchors - 1) + 2
    if trip_days == 1 and half_day:
        return min(raw, 3)
    return raw


def total_tool_budget(trip_days: int, base: int = 12, per_day: int = 6) -> int:
    return base + max(0, trip_days - 1) * per_day


def max_search_calls(trip_days: int, cap: int = 12) -> int:
    return min(4 * trip_days, cap)


def max_weather_calls(trip_days: int, cap: int = 6) -> int:
    return min(2 * trip_days, cap)


def normalize_tool_kind(name: str) -> str | None:
    s = str(name or "").replace("lifecare__", "").replace("lifecare_", "")
    if "search_places" in s:
        return "search_places"
    if "plan_route" in s:
        return "plan_route"
    if "get_weather" in s:
        return "get_weather"
    return None


def count_tools(tools_called: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"search_places": 0, "plan_route": 0, "get_weather": 0, "total": 0}
    for tc in tools_called:
        kind = normalize_tool_kind(tc.get("tool") or "")
        if kind:
            counts[kind] += 1
        counts["total"] += 1
    return counts


def check_budget(
    slots: dict[str, Any],
    tools_called: list[dict[str, Any]],
    policy: dict,
    *,
    next_tool: str | None = None,
) -> tuple[bool, str | None]:
    cfg = policy.get("tool_budget") or {}
    d = int(slots.get("trip_days") or 1)
    half = bool(slots.get("half_day"))
    anchors = int(slots.get("anchors_per_day") or 4)
    counts = count_tools(tools_called)
    kind = normalize_tool_kind(next_tool or "")
    if kind:
        counts = dict(counts)
        counts[kind] = counts.get(kind, 0) + 1
        counts["total"] = counts.get("total", 0) + 1

    max_total = total_tool_budget(d, cfg.get("base_total", 12), cfg.get("per_extra_day", 6))
    if counts["total"] > max_total:
        return False, f"tools_total>{max_total}"

    max_route = max_plan_route(d, anchors, half_day=half)
    if counts["plan_route"] > max_route:
        return False, f"plan_route_count>{max_route}"

    max_search = max_search_calls(d, cfg.get("search_cap", 12))
    if counts["search_places"] > max_search:
        return False, f"search_places>{max_search}"

    max_weather = max_weather_calls(d, cfg.get("weather_cap", 6))
    if counts["get_weather"] > max_weather:
        return False, f"get_weather>{max_weather}"

    return True, None
