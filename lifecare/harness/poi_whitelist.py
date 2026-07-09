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
    photo_urls: list[str] = field(default_factory=list)
    lng: float | None = None
    lat: float | None = None
    rating: float | None = None
    cost: str | None = None

    def __post_init__(self) -> None:
        if not self.normalized:
            self.normalized = normalize_poi_name(self.name)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "amap_place_url": self.amap_place_url,
            "poi_type": self.poi_type,
            "photo_urls": self.photo_urls,
            "location": {"lng": self.lng, "lat": self.lat}
            if self.lng is not None and self.lat is not None
            else None,
            "rating": self.rating,
            "cost": self.cost,
        }


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
        pid = str(p.get("id") or "").strip().replace(" ", "")
        name = str(p.get("name") or "").strip()
        if not pid or not name:
            continue
        url = str(p.get("amap_place_url") or f"https://www.amap.com/place/{pid}")
        ptype = str(p.get("type") or "")
        photos = [
            u for u in (p.get("photo_urls") or [])
            if isinstance(u, str) and u.startswith(("http://", "https://"))
        ][:3]
        loc = p.get("location") if isinstance(p.get("location"), dict) else {}
        lng = loc.get("lng")
        lat = loc.get("lat")
        rating: float | None = None
        cost: str | None = None
        rep = p.get("reputation") if isinstance(p.get("reputation"), dict) else {}
        gaode = rep.get("gaode") if isinstance(rep.get("gaode"), dict) else {}
        if gaode.get("rating") is not None:
            try:
                rating = float(gaode["rating"])
            except (TypeError, ValueError):
                rating = None
        raw_cost = gaode.get("cost")
        if raw_cost not in (None, ""):
            cost = str(raw_cost).strip()
        out.append(
            PoiEntry(
                id=pid,
                name=name,
                amap_place_url=url,
                poi_type=ptype,
                photo_urls=photos,
                lng=float(lng) if lng is not None else None,
                lat=float(lat) if lat is not None else None,
                rating=rating,
                cost=cost,
            )
        )
    return out


def build_whitelist_from_tools(tools_called: list[dict[str, Any]]) -> list[PoiEntry]:
    seen: dict[str, PoiEntry] = {}
    for tc in tools_called:
        tool = str(tc.get("tool") or "")
        if "search_places" not in tool:
            continue
        for entry in tc.get("pois") or []:
            if isinstance(entry, dict) and entry.get("id"):
                photos = [
                    u for u in (entry.get("photo_urls") or [])
                    if isinstance(u, str) and u.startswith(("http://", "https://"))
                ][:3]
                loc = entry.get("location") if isinstance(entry.get("location"), dict) else {}
                lng = entry.get("lng", loc.get("lng"))
                lat = entry.get("lat", loc.get("lat"))
                rating = entry.get("rating")
                cost = entry.get("cost")
                e = PoiEntry(
                    id=str(entry["id"]),
                    name=str(entry.get("name") or ""),
                    amap_place_url=str(entry.get("amap_place_url") or ""),
                    poi_type=str(entry.get("poi_type") or ""),
                    photo_urls=photos,
                    lng=float(lng) if lng is not None else None,
                    lat=float(lat) if lat is not None else None,
                    rating=float(rating) if rating is not None else None,
                    cost=str(cost).strip() if cost not in (None, "") else None,
                )
                _merge_into(seen, e)
        raw = tc.get("result_preview") or tc.get("result") or ""
        for e in extract_pois_from_tool_result(raw):
            _merge_into(seen, e)
    return list(seen.values())


def _merge_into(seen: dict[str, PoiEntry], e: PoiEntry) -> None:
    """合并同 id POI：保留已有 photo_urls / 坐标 / 评分，避免被无图来源覆盖。"""
    prev = seen.get(e.id)
    if prev is not None:
        if not e.photo_urls and prev.photo_urls:
            e.photo_urls = prev.photo_urls
        if e.lng is None and prev.lng is not None:
            e.lng = prev.lng
        if e.lat is None and prev.lat is not None:
            e.lat = prev.lat
        if e.rating is None and prev.rating is not None:
            e.rating = prev.rating
        if e.cost is None and prev.cost is not None:
            e.cost = prev.cost
    seen[e.id] = e


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


IMG_MD_RE = re.compile(r"!\[[^\]]*\]\(https?://")


def apply_poi_images(
    text: str,
    whitelist: list[PoiEntry],
    *,
    max_images: int = 4,
) -> tuple[str, list[str]]:
    """方案缺图时，按正文里已出现且命中白名单的 POI 段落补 `![](photo_url)`。

    只在正文**当前无任何 Markdown 图片**时触发（绝不改动模型自带的图）。
    一个 POI 最多补 1 张，全文上限 max_images，避免堆图。
    返回 (新正文, 已插入的图片 markdown 列表)。
    """
    if not whitelist or not text:
        return text, []
    if IMG_MD_RE.search(text):
        return text, []
    if not any(e.photo_urls for e in whitelist):
        return text, []

    inserts: list[tuple[int, str]] = []
    used: set[str] = set()
    for cand in extract_poi_candidates(text):
        if cand.source not in ("heading", "amap_link") or not cand.span:
            continue
        matched = match_poi(cand, whitelist)
        if not matched or not matched.photo_urls or matched.id in used:
            continue
        used.add(matched.id)
        nl = text.find("\n", cand.span[1])
        pos = nl if nl >= 0 else len(text)
        inserts.append((pos, f"\n\n![{matched.name}]({matched.photo_urls[0]})"))
        if len(inserts) >= max_images:
            break

    if not inserts:
        return text, []

    out = text
    applied: list[str] = []
    for pos, img in sorted(inserts, key=lambda x: x[0], reverse=True):
        out = out[:pos] + img + out[pos:]
        applied.append(img)
    return out, applied
