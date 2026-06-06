from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

AMAP_PLACE_RE = re.compile(r"https?://(?:www\.)?amap\.com/place/([A-Za-z0-9]+)")
HEADING_POI_RE = re.compile(
    r"^#{1,4}\s*(?:\d{1,2}[:：]\d{0,2}\s*)?(?:午餐|晚餐|早餐|上午|下午|晚上|参观|游览|打卡|停留)?\s*[·•\-—]?\s*(.+?)\s*$",
    re.M,
)
TABLE_POI_RE = re.compile(r"^\|\s*[^|]+\|\s*([^|]{2,40}?)\s*\|", re.M)
GENERIC_SKIP_RE = re.compile(
    r"附近|某|自行|自理|商圈内|商场内|待定|可选|推荐|午餐|晚餐|早餐|上午|下午|晚上|交通|备注|时段|做什么|安排"
)


@dataclass
class PoiEntry:
    id: str
    name: str
    amap_place_url: str
    normalized: str = ""
    poi_type: str = ""

    def __post_init__(self) -> None:
        if not self.normalized:
            self.normalized = normalize_poi_name(self.name)


@dataclass
class PoiCandidate:
    text: str
    source: str
    poi_id: str | None = None
    span: tuple[int, int] | None = None


@dataclass
class WhitelistResult:
    entries: list[PoiEntry] = field(default_factory=list)
    replacements: list[dict[str, Any]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def normalize_poi_name(name: str) -> str:
    s = (name or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"[\s·•\-—_]", "", s)
    s = re.sub(r"\((总店|分店|店)\)", "", s)
    for suffix in ("店", "餐厅", "风景名胜区", "景区", "博物馆", "购物中心", "商场"):
        if s.endswith(suffix) and len(s) > len(suffix) + 2:
            s = s[: -len(suffix)]
    return s.lower()


def extract_pois_from_tool_result(result: str) -> list[PoiEntry]:
    try:
        data = json.loads(result) if result.strip().startswith("{") else {}
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    if data.get("ok") is False or data.get("error"):
        return []
    pois = data.get("pois") or []
    out: list[PoiEntry] = []
    for p in pois:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        name = str(p.get("name") or "").strip()
        if not pid or not name:
            continue
        url = str(p.get("amap_place_url") or f"https://www.amap.com/place/{pid}")
        ptype = str(p.get("type") or "")
        out.append(PoiEntry(id=pid, name=name, amap_place_url=url, poi_type=ptype))
    return out


def build_whitelist_from_tools(tools_called: list[dict[str, Any]]) -> list[PoiEntry]:
    seen: dict[str, PoiEntry] = {}
    for tc in tools_called:
        tool = str(tc.get("tool") or "")
        if "search_places" not in tool:
            continue
        for entry in tc.get("pois") or []:
            if isinstance(entry, dict) and entry.get("id"):
                e = PoiEntry(
                    id=str(entry["id"]),
                    name=str(entry.get("name") or ""),
                    amap_place_url=str(entry.get("amap_place_url") or ""),
                    poi_type=str(entry.get("poi_type") or ""),
                )
                seen[e.id] = e
        raw = tc.get("result_preview") or tc.get("result") or ""
        for e in extract_pois_from_tool_result(raw):
            seen[e.id] = e
    return list(seen.values())


def _is_generic(name: str) -> bool:
    t = (name or "").strip()
    if len(t) < 2:
        return True
    if GENERIC_SKIP_RE.search(t) and len(t) < 8:
        return True
    if re.fullmatch(r"[\d\s:：|/-]+", t):
        return True
    return False


def extract_poi_candidates(text: str) -> list[PoiCandidate]:
    candidates: list[PoiCandidate] = []
    seen: set[str] = set()

    for m in AMAP_PLACE_RE.finditer(text):
        pid = m.group(1)
        key = f"link:{pid}"
        if key in seen:
            continue
        seen.add(key)
        label_m = re.search(r"\[([^\]]+)\]", text[max(0, m.start() - 80) : m.start()])
        label = label_m.group(1) if label_m else pid
        candidates.append(
            PoiCandidate(text=label, source="amap_link", poi_id=pid, span=(m.start(), m.end()))
        )

    for m in HEADING_POI_RE.finditer(text):
        name = m.group(1).strip()
        if _is_generic(name):
            continue
        key = f"h:{name}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append(PoiCandidate(text=name, source="heading", span=(m.start(), m.end())))

    for m in TABLE_POI_RE.finditer(text):
        cell = m.group(1).strip()
        if _is_generic(cell) or "|" in cell:
            continue
        if re.search(r"交通|备注|时段|费用|项目", cell):
            continue
        key = f"t:{cell}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append(PoiCandidate(text=cell, source="table", span=(m.start(1), m.end(1))))

    return candidates


def match_poi(candidate: PoiCandidate, whitelist: list[PoiEntry]) -> PoiEntry | None:
    if candidate.poi_id:
        for e in whitelist:
            if e.id == candidate.poi_id:
                return e
        return None
    norm = normalize_poi_name(candidate.text)
    if not norm or len(norm) < 2:
        return None
    for e in whitelist:
        if norm == e.normalized:
            return e
        if norm in e.normalized or e.normalized in norm:
            if len(norm) >= 3 and len(e.normalized) >= 3:
                return e
    return None


def _pick_replacement(candidate: PoiCandidate, whitelist: list[PoiEntry], used: set[str]) -> PoiEntry | None:
    pool = [e for e in whitelist if e.id not in used]
    if not pool:
        pool = list(whitelist)
    if not pool:
        return None
    hint = candidate.text.lower()
    for e in pool:
        if any(k in e.name for k in ("餐", "饭", "食")) and any(k in hint for k in ("餐", "饭", "食", "午", "晚")):
            return e
        if any(k in e.name for k in ("博物", "展览", "艺术")) and any(k in hint for k in ("博物", "展览", "室内")):
            return e
        if any(k in e.name for k in ("公园", "广场", "商场")) and any(k in hint for k in ("逛", "玩", "公园", "商场")):
            return e
    return pool[0]


def apply_poi_whitelist(text: str, whitelist: list[PoiEntry]) -> tuple[str, WhitelistResult]:
    result = WhitelistResult(entries=list(whitelist))
    if not whitelist:
        return text, result

    out = text
    used: set[str] = set()
    candidates = extract_poi_candidates(text)

    for cand in candidates:
        matched = match_poi(cand, whitelist)
        if matched:
            used.add(matched.id)
            continue

        result.unmatched.append(cand.text)
        repl = _pick_replacement(cand, whitelist, used)
        if not repl:
            if cand.span:
                s, e = cand.span
                out = out[:s] + out[e:]
            result.removed.append(cand.text)
            continue

        used.add(repl.id)
        old = cand.text
        new_link = f"[{repl.name} →]({repl.amap_place_url})"
        if cand.source == "amap_link" and cand.span:
            s, e = cand.span
            out = out[:s] + repl.amap_place_url + out[e:]
            link_m = re.search(r"\[[^\]]*\]", out[max(0, s - 60) : s + 20])
            if link_m:
                ls = max(0, s - 60) + link_m.start()
                le = max(0, s - 60) + link_m.end()
                out = out[:ls] + f"[{repl.name} →]" + out[le:]
        elif cand.span:
            s, e = cand.span
            out = out[:s] + repl.name + out[e:]
            if repl.amap_place_url and repl.amap_place_url not in out:
                out = out[: s + len(repl.name)] + f"（[{repl.name} →]({repl.amap_place_url})）" + out[s + len(repl.name) :]
        else:
            out = out.replace(old, repl.name, 1)

        result.replacements.append({"from": old, "to": repl.name, "id": repl.id})

    return out, result
