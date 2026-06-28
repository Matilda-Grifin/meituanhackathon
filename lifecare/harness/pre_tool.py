from __future__ import annotations

import json
from typing import Any

from lifecare.harness.budget import check_budget
from lifecare.harness.events import log_event
from lifecare.harness.policy_loader import load_policy
from lifecare.harness.session_state import get_session_key, load_state, resolve_stage, save_state
from lifecare.harness.tool_validate import normalize_tool_name, validate_tool_arguments


def _blocked_payload(rule_id: str, hint_zh: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error": "harness_blocked",
            "rule_id": rule_id,
            "hint_zh": hint_zh,
        },
        ensure_ascii=False,
    )


def _stage_allows_tool(stage: str, tool: str, policy: dict, *, planning_intent: bool = True) -> tuple[bool, str | None]:
    stages = policy.get("stages") or {}
    cfg = stages.get(stage) or {}
    norm = normalize_tool_name(tool) or tool
    short = norm.replace("lifecare_", "")

    if stage in ("light_weather", "chitchat"):
        if short == "get_weather" and stage == "light_weather":
            return True, None
        if short in ("search_places", "plan_route"):
            return False, "tool_not_allowed_in_light_mode"
        if stage == "chitchat":
            return False, "tool_not_allowed_in_chitchat"
        return True, None

    deny = [d.replace("lifecare_", "") for d in (cfg.get("deny_tools") or [])]
    if short in deny or norm in (cfg.get("deny_tools") or []):
        return False, "no_search_route_before_intake"

    allow = [a.replace("lifecare_", "") for a in (cfg.get("allow_tools") or [])]
    optional = [o.replace("lifecare_", "") for o in (cfg.get("optional_tools") or [])]
    allowed = set(allow + optional)

    if stage == "intake":
        if not planning_intent:
            return True, None
        if short in ("search_places", "plan_route"):
            return False, "no_search_route_before_intake"
        if short in allowed or short in optional:
            return True, None
        if short in ("get_weather",):
            return True, None
        if short in (
            "sandbox_catalog",
            "get_venue_queue",
            "get_attraction_crowd",
            "ride_estimate",
            "submit_mock_order",
            "inject_sandbox_failure",
        ):
            return True, None
        return False, "tool_not_allowed_in_stage"

    if stage == "followup_qa":
        if short in ("search_places", "plan_route", "get_weather"):
            return False, "tool_not_allowed_in_followup_qa"
        return True, None

    if allow and short not in allowed and optional and short not in optional:
        if stage == "planning" and short in ("sandbox_catalog", "get_venue_queue", "get_attraction_crowd", "ride_estimate", "submit_mock_order", "inject_sandbox_failure"):
            return True, None
        if short in ("search_places", "get_weather", "plan_route"):
            return True, None

    return True, None


_HINTS = {
    "no_search_route_before_intake": "槽位未齐，请先完成 travel-intake 选择题，本回合禁止搜点/算路。",
    "tool_not_allowed_in_stage": "当前对话阶段不允许调用该工具，请按 SOUL 阶段路由继续。",
    "tool_not_allowed_in_followup_qa": "用户仅在追问细节，请基于已有方案回答，勿重新搜点。",
    "tool_not_allowed_in_light_mode": "当前为轻量查询，请勿调用搜点/算路工具。",
    "tool_not_allowed_in_chitchat": "当前为闲聊，无需调用出行工具。",
    "tool_schema_invalid": "工具参数不合法，请修正后重试。",
    "tool_budget_exceeded": "本任务工具调用已达预算上限，请基于已有 POI/路线数据完成方案。",
    "retry_fuse_same_params": "相同参数已连续多次无进展，请更换关键词或基于已有结果完成方案。",
}


def check_pre_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> str | None:
    """
    返回 None 表示放行；返回 JSON 字符串表示拦截并作为 tool 结果。
    """
    session_key = get_session_key()
    policy = load_policy()
    state = load_state(session_key)
    stage = resolve_stage(state, policy)
    save_state(state)
    norm = normalize_tool_name(tool_name) or tool_name
    planning_intent = bool(state.get("planning_intent"))

    allowed, rule_id = _stage_allows_tool(stage, norm, policy, planning_intent=planning_intent)
    if not allowed and rule_id:
        log_event(
            session_key=session_key,
            phase="pre_tool",
            action="blocked",
            rule_id=rule_id,
            tool=norm,
            extra={"stage": stage},
        )
        from lifecare.harness.session_state import record_tool_call

        record_tool_call(session_key, norm, arguments or {}, _blocked_payload(rule_id, _HINTS.get(rule_id, "")), blocked=True)
        return _blocked_payload(rule_id, _HINTS.get(rule_id, "当前阶段不可调用该工具。"))

    if stage in ("planning", "followup_replan"):
        from lifecare.harness.retry_fuse import check_retry_fuse

        ok_fuse, fuse_rule = check_retry_fuse(state.get("tools_called") or [], norm, arguments or {})
        if not ok_fuse and fuse_rule:
            log_event(
                session_key=session_key,
                phase="pre_tool",
                action="blocked",
                rule_id=fuse_rule,
                tool=norm,
                extra={"stage": stage},
            )
            from lifecare.harness.session_state import record_tool_call

            record_tool_call(
                session_key,
                norm,
                arguments or {},
                _blocked_payload(fuse_rule, _HINTS.get(fuse_rule, "")),
                blocked=True,
            )
            return _blocked_payload(fuse_rule, _HINTS.get(fuse_rule, "相同参数重复调用已熔断。"))

    schema = validate_tool_arguments(norm, arguments or {})
    if schema.get("valid") is False:
        rid = "tool_schema_invalid"
        log_event(session_key=session_key, phase="pre_tool", action="blocked", rule_id=rid, tool=norm, extra=schema)
        return _blocked_payload(rid, _HINTS[rid])

    # 预算按「当前轮」计：追问改方案能重新搜点，避免整段会话累计上限卡死后续轮（丢 POI/配图）。
    cur_turn = int(state.get("turn_seq") or 0)
    turn_tools = [
        t for t in (state.get("tools_called") or [])
        if int(t.get("turn_seq") or 0) == cur_turn
    ]
    ok_budget, budget_rule = check_budget(
        state.get("slots") or {},
        turn_tools,
        policy,
        next_tool=norm,
    )
    if not ok_budget and budget_rule:
        kind = norm.replace("lifecare_", "")
        if kind in budget_rule or "tools_total" in budget_rule:
            log_event(
                session_key=session_key,
                phase="pre_tool",
                action="blocked",
                rule_id=budget_rule,
                tool=norm,
            )
            return _blocked_payload("tool_budget_exceeded", _HINTS["tool_budget_exceeded"])

    return None
