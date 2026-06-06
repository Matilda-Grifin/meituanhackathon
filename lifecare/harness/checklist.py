from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PLAN_MARKER_RE = re.compile(r"行程速览|##\s*📋|时段\s*\|\s*做什么")
WEATHER_SECTION_RE = re.compile(r"##\s*(?:🌤|天气|出行日天气|明日天气)|出行日天气|明日天气")
BUDGET_SECTION_RE = re.compile(r"##\s*💰|预算参考|预算表|费用参考")
ROUTE_MINUTES_RE = re.compile(r"(?:打车|驾车|约)\s*\d+\s*(?:km|公里|分钟|min)|\d+\s*分钟\s*/\s*\d+\s*(?:km|公里)")
TIMEBLOCK_RE = re.compile(r"^#{2,4}\s+\d{1,2}[:：]", re.M)
AMAP_LINK_RE = re.compile(r"amap\.com/place/")


@dataclass
class ChecklistResult:
    missing: list[str] = field(default_factory=list)
    patches_applied: list[str] = field(default_factory=list)
    ok: bool = True


def _called_weather(tools_called: list[dict[str, Any]]) -> bool:
    for tc in tools_called:
        if "get_weather" in str(tc.get("tool") or "") and tc.get("ok") is not False:
            return True
    return False


def _called_route(tools_called: list[dict[str, Any]]) -> bool:
    for tc in tools_called:
        if "plan_route" in str(tc.get("tool") or "") and tc.get("ok") is not False:
            return True
    return False


def _called_search(tools_called: list[dict[str, Any]]) -> bool:
    for tc in tools_called:
        if "search_places" in str(tc.get("tool") or "") and tc.get("ok") is not False:
            pois = tc.get("pois") or []
            if pois:
                return True
    return False


def run_checklist(
    text: str,
    tools_called: list[dict[str, Any]],
    *,
    tools_degraded: bool = False,
) -> ChecklistResult:
    result = ChecklistResult()
    t = text or ""

    if not PLAN_MARKER_RE.search(t):
        result.missing.append("structure_overview")
    if not (TIMEBLOCK_RE.search(t) or re.search(r"分时段|上午|下午|12[:：]00", t)):
        result.missing.append("structure_timeline")

    if _called_weather(tools_called):
        if not WEATHER_SECTION_RE.search(t):
            result.missing.append("weather_block")
    elif not tools_degraded:
        result.missing.append("weather_tool")

    if not BUDGET_SECTION_RE.search(t):
        result.missing.append("budget_block")

    if _called_route(tools_called):
        if not ROUTE_MINUTES_RE.search(t):
            result.missing.append("route_minutes")
    elif not tools_degraded:
        result.missing.append("route_tool")

    if _called_search(tools_called) and not tools_degraded:
        if not AMAP_LINK_RE.search(t):
            result.missing.append("poi_links")

    result.ok = len(result.missing) == 0
    return result


def apply_checklist_patches(text: str, missing: list[str], *, tools_degraded: bool = False) -> tuple[str, list[str]]:
    out = text
    applied: list[str] = []

    if "weather_block" in missing:
        block = (
            "## 🌤 出行日天气\n\n"
            "请以出发前高德/系统天气 App 为准；若工具返回日期与出行日不一致，出发前请再次确认。\n"
        )
        if not WEATHER_SECTION_RE.search(out):
            insert_at = re.search(r"##\s*📋|行程速览", out)
            if insert_at:
                out = out[: insert_at.start()] + block + "\n" + out[insert_at.start() :]
            else:
                out = block + "\n" + out
            applied.append("weather_block")

    if "budget_block" in missing:
        block = (
            "## 💰 预算参考（估算）\n\n"
            "| 项目 | 费用（元） |\n"
            "|---|---|\n"
            "| 交通 | 待到店确认 |\n"
            "| 餐饮 | 待到店确认 |\n"
            "| 门票 | 待到店确认 |\n"
            "| **合计** | **仅供参考** |\n"
        )
        if not BUDGET_SECTION_RE.search(out):
            out = out.rstrip() + "\n\n" + block
            applied.append("budget_block")

    if "route_minutes" in missing and not tools_degraded:
        note = "> 路段交通：相邻锚点间请参考上文表格「交通」列或出发前用高德导航确认分钟数/公里数。\n"
        if not ROUTE_MINUTES_RE.search(out):
            m = re.search(r"##\s*📋|行程速览", out)
            if m:
                end = out.find("\n## ", m.end())
                pos = end if end > 0 else len(out)
                out = out[:pos] + "\n\n" + note + out[pos:]
            applied.append("route_minutes_note")

    if "structure_overview" in missing:
        block = (
            "## 📋 行程速览\n\n"
            "| 时段 | 做什么 | 交通 | 备注 |\n"
            "|---|---|---|---|\n"
            "| 待排 | 见下分时段 | — | — |\n"
        )
        if not PLAN_MARKER_RE.search(out):
            out = block + "\n" + out
            applied.append("structure_overview")

    return out, applied
