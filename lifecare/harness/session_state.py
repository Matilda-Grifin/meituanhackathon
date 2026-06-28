from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from lifecare.harness.slots import (
    Slots,
    detect_chitchat,
    detect_city_change,
    detect_full_plan,
    detect_light_weather,
    detect_planning_intent,
    detect_qa_intent,
    detect_replan_intent,
    parse_slots_from_messages,
)

_LOCK = threading.Lock()


def _state_dir() -> Path:
    raw = os.environ.get("LIFECARE_HARNESS_STATE_DIR", "").strip()
    if raw:
        p = Path(raw)
    else:
        home = Path(os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw")))
        p = home / "harness_state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sanitize_session_key(key: str) -> str:
    s = re.sub(r"[^\w\-.:@]+", "_", (key or "default").strip())[:180]
    return s or "default"


def get_session_key() -> str:
    env_key = os.environ.get("LIFECARE_HARNESS_SESSION_KEY", "").strip()
    if env_key:
        return _sanitize_session_key(env_key)
    active = _state_dir() / "_active_session.txt"
    if active.is_file():
        return _sanitize_session_key(active.read_text(encoding="utf-8").strip() or "default")
    return "default"


def set_active_session(session_key: str) -> None:
    sk = _sanitize_session_key(session_key)
    (_state_dir() / "_active_session.txt").write_text(sk, encoding="utf-8")


def _state_path(session_key: str) -> Path:
    return _state_dir() / f"{_sanitize_session_key(session_key)}.json"


def _default_state() -> dict[str, Any]:
    return {
        "session_key": "default",
        "stage": "intake",
        "planning_intent": False,
        "slots": Slots().to_dict(),
        "has_full_plan": False,
        "intake_consumed": False,
        "intake_mode": None,
        "tools_degraded": False,
        "search_degraded": False,
        "weather_degraded": False,
        "consecutive_tool_failures": 0,
        "turn_seq": 0,
        "tools_called": [],
        "user_messages": [],
        "last_user_message": "",
    }


def load_state(session_key: str | None = None) -> dict[str, Any]:
    sk = _sanitize_session_key(session_key or get_session_key())
    path = _state_path(sk)
    with _LOCK:
        if not path.is_file():
            st = _default_state()
            st["session_key"] = sk
            return st
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = _default_state()
        data.setdefault("session_key", sk)
        return data


def save_state(state: dict[str, Any]) -> None:
    sk = _sanitize_session_key(state.get("session_key") or get_session_key())
    state["session_key"] = sk
    path = _state_path(sk)
    with _LOCK:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_stage(state: dict[str, Any], policy: dict[str, Any]) -> str:
    slots = state.get("slots") or {}
    last_user = state.get("last_user_message") or ""
    msgs = state.get("user_messages") or []
    blob = "\n".join(msgs)
    has_plan = bool(state.get("has_full_plan"))
    planning_intent = detect_planning_intent(blob) or (has_plan and not detect_light_weather(last_user, blob))
    if slots.get("ready") and (slots.get("intake_submitted") or slots.get("intake_consumed")):
        planning_intent = True
    state["planning_intent"] = planning_intent

    if detect_light_weather(last_user, blob) and not has_plan:
        return "light_weather"
    if detect_chitchat(last_user) and not has_plan and not planning_intent:
        return "chitchat"
    if not planning_intent and not has_plan:
        return "chitchat"

    if has_plan and detect_city_change(last_user, slots.get("city")):
        state["has_full_plan"] = False
        slots = dict(slots)
        slots["ready"] = False
        state["slots"] = slots
        return "intake"

    if not slots.get("ready"):
        return "intake"
    if has_plan:
        if detect_replan_intent(last_user):
            return "followup_replan"
        if detect_qa_intent(last_user, has_plan):
            return "followup_qa"
        if re.search(r"改|换|重新", last_user):
            return "followup_replan"
        return "followup_qa"
    return "planning"


def on_user_message(session_key: str, message: str, *, intake_skipped: bool = False) -> dict[str, Any]:
    state = load_state(session_key)
    msgs = list(state.get("user_messages") or [])
    msg = (message or "").strip()
    if msg and not msg.startswith("[位置上下文]"):
        if not msgs or msgs[-1] != msg:
            msgs.append(msg)
        # 每条真实用户消息开启新一轮：工具预算按轮计（追问改方案能重新搜点），
        # 而非整段会话累计（否则第 3~4 轮搜索被 4 次/会话的上限卡死，丢 POI/配图）。
        state["turn_seq"] = int(state.get("turn_seq") or 0) + 1
    state["user_messages"] = msgs[-30:]
    state["last_user_message"] = msg
    slots = parse_slots_from_messages(msgs)
    if intake_skipped and not slots.intake_submitted:
        slots.intake_consumed = True
        slots.intake_mode = "skipped_freetext"
        if detect_planning_intent("\n".join(msgs)):
            slots.ready = True
    state["slots"] = slots.to_dict()
    state["intake_consumed"] = bool(slots.intake_consumed)
    state["intake_mode"] = slots.intake_mode
    set_active_session(session_key)
    from lifecare.harness.policy_loader import load_policy

    state["stage"] = resolve_stage(state, load_policy())
    save_state(state)
    return state


def on_assistant_message(session_key: str, text: str) -> dict[str, Any]:
    state = load_state(session_key)
    if detect_full_plan(text or ""):
        state["has_full_plan"] = True
    from lifecare.harness.policy_loader import load_policy

    state["stage"] = resolve_stage(state, load_policy())
    save_state(state)
    return state


def record_tool_call(
    session_key: str,
    tool: str,
    arguments: dict[str, Any] | None,
    result: str,
    *,
    blocked: bool = False,
) -> dict[str, Any]:
    from lifecare.harness.poi_whitelist import extract_pois_from_tool_result
    from lifecare.harness.retry_fuse import _is_empty_or_failed, _tool_fingerprint

    state = load_state(session_key)
    ok = True
    err = None
    empty_or_failed = False
    if blocked:
        ok = False
        err = "harness_blocked"
    else:
        try:
            data = json.loads(result) if result.strip().startswith("{") else {}
            if isinstance(data, dict):
                ok = data.get("ok", True) is not False and not data.get("error")
                err = data.get("error")
                # CUQPS 是高德瞬时限流：err 已使 ok=False，按「该工具失败」走下方计数/恢复，
                # 不再因任意一次工具限流就立刻全局 search/tools degraded（曾导致一次 plan_route
                # 限流毒化整段会话、后续轮无 POI 链接与配图）。
        except json.JSONDecodeError:
            ok = True
        empty_or_failed = _is_empty_or_failed(result)

    pois: list[dict[str, Any]] = []
    if "search_places" in (tool or "") and not blocked:
        for p in extract_pois_from_tool_result(result):
            pois.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "amap_place_url": p.amap_place_url,
                    "poi_type": p.poi_type,
                    "photo_urls": p.photo_urls,
                }
            )

    entry = {
        "tool": tool,
        "turn_seq": int(state.get("turn_seq") or 0),
        "ok": ok,
        "error": err,
        "blocked": blocked,
        "arguments": arguments or {},
        "fingerprint": _tool_fingerprint(tool, arguments),
        "empty_or_failed": empty_or_failed,
        "result_preview": (result or "")[:4000],
        "pois": pois,
    }
    tools = list(state.get("tools_called") or [])
    tools.append(entry)
    state["tools_called"] = tools[-80:]

    if not ok and not blocked:
        fails = int(state.get("consecutive_tool_failures") or 0) + 1
        state["consecutive_tool_failures"] = fails
        # 单工具失败只标记其专属 degraded；tools_degraded 需「连续」失败才升级，
        # 避免单次瞬时限流（尤其是 plan_route）就把整段会话判为降级。
        if "get_weather" in (tool or ""):
            state["weather_degraded"] = True
        if "search_places" in (tool or ""):
            state["search_degraded"] = True
        if fails >= 2:
            state["tools_degraded"] = True
    elif ok and not empty_or_failed:
        # 工具恢复成功：清掉对应 degraded，避免一次瞬时失败永久毒化后续多轮。
        state["consecutive_tool_failures"] = 0
        if "search_places" in (tool or ""):
            state["search_degraded"] = False
        if "get_weather" in (tool or ""):
            state["weather_degraded"] = False
        if not state.get("search_degraded") and not state.get("weather_degraded"):
            state["tools_degraded"] = False

    save_state(state)
    return state
