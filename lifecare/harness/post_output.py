from __future__ import annotations

import re
from typing import Any

from lifecare.harness.checklist import apply_checklist_patches, run_checklist
from lifecare.harness.events import log_audit, log_event
from lifecare.harness.poi_whitelist import apply_poi_whitelist, build_whitelist_from_tools
from lifecare.harness.policy_loader import load_policy, load_repairs
from lifecare.harness.session_state import load_state, on_assistant_message, resolve_stage


INTAKE_ONLY_RE = re.compile(
    r"(第\s*1\s*题|^\s*1[\.、．]\s|选择题答案：|全部用默认|直接回复)",
    re.M,
)
PLAN_MARKER_RE = re.compile(r"行程速览|##\s*📋|##\s*💰|预算参考|时段\s*\|\s*做什么")
IMAGE_BUBBLE_RE = re.compile(r"##\s*📸\s*行程一览图")
ACK_ONLY_RE = re.compile(r"^(好的|收到|明白|正在查|正在并行)[^#]{0,200}$")


def should_apply_harness_output(text: str) -> bool:
    """与前端气泡逻辑对齐：不处理选择题、ack、生图、纯噪声。"""
    t = (text or "").strip()
    if not t or len(t) < 40:
        return False
    if IMAGE_BUBBLE_RE.search(t):
        return False
    if ACK_ONLY_RE.match(t) and not PLAN_MARKER_RE.search(t):
        return False
    if INTAKE_ONLY_RE.search(t) and not PLAN_MARKER_RE.search(t):
        if len(t) < 900:
            return False
    return True


def _output_flags(text: str, state: dict[str, Any]) -> dict[str, bool]:
    t = text or ""
    return {
        "not_party_size": not bool((state.get("slots") or {}).get("party_size")),
        "tools_degraded": bool(state.get("tools_degraded")),
        "uses_mock_reputation": bool(
            re.search(r"口碑|好评|评分|review_count|mock|演示", t, re.I)
        ),
        "mentions_reviews": bool(re.search(r"评价|点评|评论|口碑", t)),
        "has_budget_table": bool(re.search(r"##\s*💰|预算参考|预算|费用参考", t)),
        "has_museum_or_booking_section": bool(
            re.search(r"博物|预约|闭馆|小程序", t)
        ),
    }


def _template_text(repairs: dict, template_id: str) -> str:
    templates = repairs.get("templates") or {}
    raw = templates.get(template_id) or ""
    return str(raw).strip()


def _contains_marker(text: str, marker: str | None) -> bool:
    if not marker:
        return False
    return marker in text


def _strip_patterns(text: str, patterns: list[str]) -> tuple[str, list[str]]:
    applied = []
    out = text
    for pat in patterns:
        new = re.sub(pat, "", out, flags=re.M)
        if new != out:
            applied.append(pat)
            out = new
    return out.strip(), applied


def _prepend_if_missing(text: str, block: str, marker: str | None) -> tuple[str, bool]:
    if _contains_marker(text, marker) or block in text:
        return text, False
    return f"{block}\n\n{text.lstrip()}", True


def _append_if_missing(text: str, block: str, marker: str | None) -> tuple[str, bool]:
    if _contains_marker(text, marker) or block in text:
        return text, False
    sep = "\n\n" if not text.endswith("\n") else "\n"
    return f"{text.rstrip()}{sep}{block}\n", True


def _insert_after_budget(text: str, block: str, marker: str | None) -> tuple[str, bool]:
    if _contains_marker(text, marker) or block in text:
        return text, False
    m = re.search(r"(##\s*💰[^\n]*\n(?:[\s\S]*?)(?=\n##\s|\Z))", text)
    if m:
        pos = m.end()
        return text[:pos].rstrip() + f"\n\n{block}\n" + text[pos:].lstrip(), True
    return _append_if_missing(text, block, marker)


def _is_full_plan_stage(state: dict[str, Any], policy: dict) -> bool:
    stage = resolve_stage(state, policy)
    return stage in ("planning", "followup_replan") and bool(state.get("planning_intent", True))


def _strip_fake_amap_when_degraded(text: str) -> tuple[str, bool]:
    if not re.search(r"amap\.com/place/", text):
        return text, False
    out = re.sub(r"\[([^\]]+)\]\(https?://(?:www\.)?amap\.com/place/[^)]+\)", r"\1", text)
    out = re.sub(r"https?://(?:www\.)?amap\.com/place/[A-Za-z0-9]+", "", out)
    return out, out != text


def validate_and_repair(
    session_key: str,
    text: str,
    *,
    apply_repairs: bool = True,
) -> dict[str, Any]:
    """
    校验助手输出并按 repairs.yaml 修复。不修改选择题/ack/生图气泡（调用方应先调 should_apply_harness_output）。
    """
    policy = load_policy()
    repairs = load_repairs()
    state = load_state(session_key)
    flags = _output_flags(text, state)
    violations: list[dict[str, Any]] = []
    repairs_applied: list[str] = []
    checklist_missing: list[str] = []
    poi_audit: dict[str, Any] = {}

    for rule in policy.get("output_forbidden") or []:
        when = rule.get("when") or ""
        if when == "not_party_size" and not flags["not_party_size"]:
            continue
        if when == "tools_degraded" and not flags["tools_degraded"]:
            continue
        if when == "search_degraded" and not state.get("search_degraded"):
            continue
        if when == "weather_degraded" and not state.get("weather_degraded"):
            continue
        if when == "mentions_reviews" and not flags["mentions_reviews"]:
            continue
        for pat in rule.get("patterns") or []:
            if re.search(pat, text):
                unless = rule.get("unless_contains") or []
                if unless and any(u in text for u in unless):
                    continue
                violations.append({"id": rule.get("id"), "pattern": pat, "severity": rule.get("severity")})
                log_event(
                    session_key=session_key,
                    phase="post_output",
                    action="violation",
                    rule_id=rule.get("id"),
                    extra={"pattern": pat},
                )

    out = text
    if apply_repairs:
        for rr in repairs.get("rules") or []:
            match = rr.get("match") or ""
            action = rr.get("action")
            tid = rr.get("template_id")
            marker = rr.get("marker")
            block = _template_text(repairs, tid) if tid else ""

            if match == "output_forbidden.no_preset_party_size" and flags["not_party_size"]:
                if action == "strip_patterns":
                    out, stripped = _strip_patterns(out, rr.get("strip_patterns") or [])
                    if stripped:
                        repairs_applied.append("strip_party_size")

            elif match == "output_required.mock_disclaimer" and flags["uses_mock_reputation"]:
                if action == "append_if_missing" and block:
                    out, ok = _append_if_missing(out, block, marker)
                    if ok:
                        repairs_applied.append("mock_disclaimer")

            elif match == "output_required.budget_estimate_notice" and flags["has_budget_table"]:
                if action == "append_if_missing" and block:
                    out, ok = _insert_after_budget(out, block, marker)
                    if ok:
                        repairs_applied.append("budget_estimate_notice")

            elif match == "output_required.tool_degraded_notice" and flags["tools_degraded"]:
                if action == "prepend_if_missing" and block:
                    out, ok = _prepend_if_missing(out, block, marker)
                    if ok:
                        repairs_applied.append("tool_degraded_notice")

            elif match == "output_required.search_degraded_notice" and state.get("search_degraded"):
                if action == "prepend_if_missing" and block:
                    out, ok = _prepend_if_missing(out, block, marker)
                    if ok:
                        repairs_applied.append("search_degraded_notice")

            elif match == "output_required.weather_degraded_notice" and state.get("weather_degraded"):
                if action == "prepend_if_missing" and block:
                    out, ok = _prepend_if_missing(out, block, marker)
                    if ok:
                        repairs_applied.append("weather_degraded_notice")

            elif match == "output_required.booking_reminder" and flags["has_museum_or_booking_section"]:
                if action == "append_if_missing" and block:
                    out, ok = _append_if_missing(out, block, marker)
                    if ok:
                        repairs_applied.append("booking_reminder")

        if _is_full_plan_stage(state, policy) and should_apply_harness_output(out):
            tools_called = state.get("tools_called") or []
            degraded = bool(state.get("tools_degraded"))
            cl = run_checklist(out, tools_called, tools_degraded=degraded)
            checklist_missing = cl.missing
            if cl.missing:
                out, patches = apply_checklist_patches(out, cl.missing, tools_degraded=degraded)
                repairs_applied.extend(patches)

            if state.get("search_degraded"):
                out, stripped = _strip_fake_amap_when_degraded(out)
                if stripped:
                    repairs_applied.append("strip_fake_amap_urls")

            whitelist = build_whitelist_from_tools(tools_called)
            if whitelist and not state.get("search_degraded"):
                out, wl_result = apply_poi_whitelist(out, whitelist)
                if wl_result.replacements or wl_result.removed or wl_result.unmatched:
                    repairs_applied.append("poi_whitelist")
                    poi_audit = {
                        "replacements": wl_result.replacements,
                        "removed": wl_result.removed,
                        "unmatched": wl_result.unmatched,
                        "whitelist_size": len(whitelist),
                    }
                    log_audit(
                        session_key=session_key,
                        action="poi_whitelist",
                        extra=poi_audit,
                    )

    on_assistant_message(session_key, out)

    return {
        "ok": True,
        "text": out,
        "blocked": False,
        "violations": violations,
        "repairs_applied": repairs_applied,
        "checklist_missing": checklist_missing,
        "poi_audit": poi_audit,
        "skipped": not should_apply_harness_output(text),
    }
