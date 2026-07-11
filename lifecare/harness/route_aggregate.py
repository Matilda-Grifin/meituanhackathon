from __future__ import annotations

import json
import re
from typing import Any

from lifecare.clients import amap as amap_client
from lifecare.harness.poi_whitelist import (
    PoiEntry,
    build_whitelist_from_tools,
    extract_poi_candidates,
    match_poi,
)


def _decode_polyline(polyline: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for pair in (polyline or "").split(";"):
        pair = pair.strip()
        if "," not in pair:
            continue
        lng_s, lat_s = pair.split(",", 1)
        try:
            out.append((float(lng_s), float(lat_s)))
        except ValueError:
            continue
    return out


def _merge_paths(segments: list[list[dict[str, float]]]) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for seg in segments:
        for pt in seg:
            if merged and merged[-1]["lng"] == pt["lng"] and merged[-1]["lat"] == pt["lat"]:
                continue
            merged.append(pt)
    return merged


def _path_from_steps(steps: list[dict[str, Any]]) -> list[dict[str, float]]:
    pts: list[dict[str, float]] = []
    for step in steps:
        for lng, lat in _decode_polyline(str(step.get("polyline") or "")):
            if pts and pts[-1]["lng"] == lng and pts[-1]["lat"] == lat:
                continue
            pts.append({"lng": lng, "lat": lat})
    return pts


def ordered_plan_poi_ids(plan_text: str, whitelist: list[PoiEntry]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for cand in extract_poi_candidates(plan_text):
        matched = match_poi(cand, whitelist)
        if not matched or matched.id in seen:
            continue
        if matched.lng is None or matched.lat is None:
            continue
        seen.add(matched.id)
        ordered.append(matched.id)

    if len(ordered) < 2:
        for e in whitelist:
            if e.id in seen or e.lng is None or e.lat is None:
                continue
            seen.add(e.id)
            ordered.append(e.id)
            if len(ordered) >= 8:
                break
    return ordered


def _infer_mode(text: str) -> str:
    if re.search(r"驾车|自驾|开车", text):
        return "driving"
    if re.search(r"打车|出租|网约车", text):
        return "taxi"
    if re.search(r"地铁|公交|乘车|轻轨", text):
        return "transit"
    if re.search(r"骑行|骑车|单车", text):
        return "bicycling"
    if re.search(r"步行|走路|徒步", text):
        return "walking"
    return "unknown"


def _text_between(plan_text: str, from_name: str, to_name: str) -> str:
    start = plan_text.find(from_name)
    if start < 0:
        return ""
    start += len(from_name)
    end = plan_text.find(to_name, start)
    if end < 0:
        return plan_text[start : start + 500]
    return plan_text[start:end]


def _parse_distance_duration(text: str) -> tuple[int | None, int | None]:
    distance_m: int | None = None
    duration_s: int | None = None

    km_m = re.search(r"(?:全程约?|约)?\s*(\d+(?:\.\d+)?)\s*(?:公里|km)", text, re.I)
    if km_m:
        distance_m = int(float(km_m.group(1)) * 1000)

    m_m = re.search(r"(?:步行约?|约)\s*(\d+)\s*(?:米|m)(?!\w)", text, re.I)
    if m_m:
        distance_m = int(m_m.group(1))

    min_m = re.search(r"(?:车程约?|约|需要)?\s*(\d+)\s*分钟", text)
    if min_m:
        duration_s = int(min_m.group(1)) * 60

    return distance_m, duration_s


def _leg_icon(mode: str) -> str:
    if mode in ("driving", "taxi"):
        return "🚗"
    if mode == "transit":
        return "🚇"
    if mode == "bicycling":
        return "🚲"
    return "🚶"


def _build_leg_label(mode: str, distance_m: int, duration_s: int) -> str:
    km = (
        f"{distance_m / 1000:.1f}km"
        if distance_m >= 1000
        else f"{int(distance_m)}m"
    )
    minutes = max(1, round(duration_s / 60))
    return f"{_leg_icon(mode)} {km} · {minutes}分钟"


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    import math

    r = 6371000.0
    to_rad = math.radians
    d_lat = to_rad(lat2 - lat1)
    d_lng = to_rad(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(to_rad(lat1)) * math.cos(to_rad(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _plan_route(
    mode: str,
    o_lng: float,
    o_lat: float,
    d_lng: float,
    d_lat: float,
    *,
    include_polyline: bool,
) -> dict[str, Any]:
    if mode in ("driving", "taxi"):
        return amap_client.plan_route_driving(
            o_lng, o_lat, d_lng, d_lat, include_polyline=include_polyline
        )
    return amap_client.plan_route_walking(
        o_lng, o_lat, d_lng, d_lat, include_polyline=include_polyline
    )


def build_session_route(
    tools_called: list[dict[str, Any]],
    plan_text: str = "",
    *,
    include_polyline: bool = False,
) -> dict[str, Any]:
    whitelist = build_whitelist_from_tools(tools_called)
    by_id = {e.id: e for e in whitelist}
    ordered_ids = ordered_plan_poi_ids(plan_text, whitelist)
    ordered = [by_id[i] for i in ordered_ids if i in by_id]

    if len(ordered) < 2:
        return {
            "ok": True,
            "route": {
                "ordered_poi_ids": ordered_ids,
                "legs": [],
                "total_distance_m": 0,
                "total_duration_s": 0,
                "path": [],
            },
        }

    tool_legs: list[dict[str, Any]] = []
    for tc in tools_called:
        tool = str(tc.get("tool") or "")
        if "plan_route" not in tool:
            continue
        args = tc.get("arguments") or {}
        raw = tc.get("result_preview") or ""
        try:
            data = json.loads(raw) if raw.strip().startswith("{") else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not data.get("ok"):
            continue
        tool_legs.append(
            {
                "origin": (
                    float(args.get("origin_lng")),
                    float(args.get("origin_lat")),
                ),
                "dest": (
                    float(args.get("dest_lng")),
                    float(args.get("dest_lat")),
                ),
                "mode": str(data.get("mode") or args.get("mode") or "walking"),
                "distance_m": int(data.get("distance_m") or 0),
                "duration_s": int(data.get("duration_s") or 0),
                "path": data.get("path") or [],
                "source": "tool",
            }
        )

    legs: list[dict[str, Any]] = []
    path_segments: list[list[dict[str, float]]] = []

    for i in range(1, len(ordered)):
        prev_e = ordered[i - 1]
        next_e = ordered[i]
        between = _text_between(plan_text, prev_e.name, next_e.name)
        mode = _infer_mode(between)
        if mode == "unknown":
            mode = "walking"
        route_mode = "driving" if mode in ("driving", "taxi") else "walking"

        parsed_dist, parsed_dur = _parse_distance_duration(between)
        leg_path: list[dict[str, float]] = []
        distance_m = parsed_dist
        duration_s = parsed_dur
        source = "plan_text" if (parsed_dist or parsed_dur) else "estimated"

        matched_tool = None
        for tl in tool_legs:
            if (
                prev_e.lng is not None
                and prev_e.lat is not None
                and next_e.lng is not None
                and next_e.lat is not None
                and abs(tl["origin"][0] - prev_e.lng) < 0.02
                and abs(tl["origin"][1] - prev_e.lat) < 0.02
                and abs(tl["dest"][0] - next_e.lng) < 0.02
                and abs(tl["dest"][1] - next_e.lat) < 0.02
            ):
                matched_tool = tl
                break

        if matched_tool:
            distance_m = matched_tool["distance_m"] or distance_m
            duration_s = matched_tool["duration_s"] or duration_s
            leg_path = matched_tool.get("path") or []
            source = "tool"
            mode = matched_tool.get("mode") or mode
        elif (
            prev_e.lng is not None
            and prev_e.lat is not None
            and next_e.lng is not None
            and next_e.lat is not None
        ):
            api = _plan_route(
                route_mode,
                prev_e.lng,
                prev_e.lat,
                next_e.lng,
                next_e.lat,
                include_polyline=include_polyline,
            )
            if api.get("ok"):
                distance_m = int(api.get("distance_m") or distance_m or 0)
                duration_s = int(api.get("duration_s") or duration_s or 0)
                leg_path = api.get("path") or []
                source = "tool" if leg_path else source

        if distance_m is None or distance_m <= 0:
            if (
                prev_e.lng is not None
                and prev_e.lat is not None
                and next_e.lng is not None
                and next_e.lat is not None
            ):
                distance_m = int(
                    _haversine_m(prev_e.lng, prev_e.lat, next_e.lng, next_e.lat)
                )
            else:
                distance_m = 0
            source = "estimated"
        if duration_s is None or duration_s <= 0:
            speed = 1.2 if route_mode == "walking" else 8.0
            duration_s = max(60, int(distance_m / speed))

        legs.append(
            {
                "from_poi_id": prev_e.id,
                "to_poi_id": next_e.id,
                "mode": mode if mode != "unknown" else route_mode,
                "distance_m": distance_m,
                "duration_s": duration_s,
                "label": _build_leg_label(
                    mode if mode != "unknown" else route_mode,
                    int(distance_m),
                    int(duration_s),
                ),
                "source": source,
            }
        )
        if leg_path:
            path_segments.append(leg_path)

    total_distance_m = sum(int(l.get("distance_m") or 0) for l in legs)
    total_duration_s = sum(int(l.get("duration_s") or 0) for l in legs)
    merged_path = _merge_paths(path_segments)

    return {
        "ok": True,
        "route": {
            "ordered_poi_ids": ordered_ids,
            "legs": legs,
            "total_distance_m": total_distance_m,
            "total_duration_s": total_duration_s,
            "path": merged_path if include_polyline else [],
        },
    }
