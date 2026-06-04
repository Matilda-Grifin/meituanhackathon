"""
POI「口碑/情感」用于排序权重：优先用高德 extensions=all 返回的 rating；
若无或需稳定全国可测的辅助量，则用 **确定性 mock**（同一 poi_id + 城市 + 类型 永远相同）。

说明：高德 Web 服务 **不提供** 与美团/点评等价的逐条评论文本；rating/cost 仅部分类目返回。
mock 层模拟的是「好评率先验 + 评论量量级 + 情感标签」，便于黑客松在全境任意 POI 上做可复现测试。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def _digest_seed(parts: tuple[str, ...]) -> int:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:12], "big")


def _parse_biz_ext(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s in ("[]", "{}"):
            return {}
        try:
            o = json.loads(s)
            return o if isinstance(o, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def extract_gaode_biz(poi_raw: dict[str, Any]) -> dict[str, Any]:
    """从高德 POI 原始 dict 抽取 biz_ext 中的 rating / cost（若有）。"""
    be = _parse_biz_ext(poi_raw.get("biz_ext"))
    rating = be.get("rating")
    cost = be.get("cost")
    out_rating: float | None = None
    if rating is not None and str(rating).strip() != "":
        try:
            out_rating = float(rating)
        except (TypeError, ValueError):
            out_rating = None
    return {"rating": out_rating, "cost": str(cost).strip() if cost not in (None, "") else None}


def _type_bucket(poi_type: str) -> str:
    t = poi_type or ""
    if re.search(r"风景名胜|景点|公园|博物馆|文化|艺术馆|游乐", t):
        return "scenic_culture"
    if re.search(r"餐饮|美食|咖啡|茶座|甜品|小吃|餐厅|饭", t):
        return "dining"
    return "other"


def deterministic_mock(poi_id: str, city: str, poi_type: str) -> dict[str, Any]:
    """全国任意 POI 可生成稳定伪指标（非真实评论库）。"""
    bucket = _type_bucket(poi_type)
    n = _digest_seed(("lifecare-mock-rep-v1", str(poi_id), str(city), bucket, poi_type[:80]))
    # 星级 3.2–4.9
    mock_star = 3.2 + (n % 1800) / 1000.0
    mock_star = round(min(4.9, mock_star), 2)
    # 好评率先验 0.48–0.94
    pos = 0.48 + (n // 1000 % 4700) / 10000.0
    pos = round(min(0.94, pos), 4)
    # 伪评论量（量级）
    reviews = 12 + (n // 10_000 % 2800)
    # 情感标签（由 pos 决定，mock 内部一致）
    if pos >= 0.72:
        label = "正面居多"
    elif pos >= 0.55:
        label = "中性"
    else:
        label = "偏负面"
    return {
        "mock_star": mock_star,
        "positive_ratio_proxy": pos,
        "review_count_proxy": reviews,
        "sentiment_label": label,
        "type_bucket": bucket,
    }


def build_reputation_for_poi(
    poi_raw: dict[str, Any],
    *,
    city: str,
    attach_mock: bool,
) -> dict[str, Any]:
    """
    合并高德（若有）与 mock，输出给 Agent 做权重字段。
    poi_raw: 高德 place/text 单条 POI 原始字典。
    """
    pid = str(poi_raw.get("id") or "")
    name = str(poi_raw.get("name") or "")
    ptype = str(poi_raw.get("type") or "")
    gaode = extract_gaode_biz(poi_raw)
    g_rating = gaode["rating"]

    if not attach_mock:
        if g_rating is not None:
            return {
                "gaode": gaode,
                "mock_baseline": {},
                "for_weights": {
                    "star_for_rank": round(g_rating, 2),
                    "positive_ratio_proxy": round(g_rating / 5.0, 4),
                    "review_count_proxy": None,
                    "sentiment_label": "仅高德分(无mock)",
                },
                "source": "gaode_only",
                "_note": "未启用 mock；无高德 rating 时无可信口碑分。",
            }
        return {
            "gaode": gaode,
            "mock_baseline": {},
            "for_weights": {
                "star_for_rank": None,
                "positive_ratio_proxy": None,
                "review_count_proxy": None,
                "sentiment_label": "无",
            },
            "source": "no_reputation_data",
            "_note": "高德无 rating 且未启用 mock。",
        }

    mock = deterministic_mock(pid or name, city, ptype)

    if g_rating is not None:
        blend_star = round(0.65 * g_rating + 0.35 * mock.get("mock_star", g_rating), 2)
        pos = round(0.5 * (g_rating / 5.0) + 0.5 * mock.get("positive_ratio_proxy", g_rating / 5.0), 4)
        source = "gaode_rating+mock_prior"
    else:
        blend_star = mock.get("mock_star", 4.0)
        pos = mock.get("positive_ratio_proxy", 0.7)
        source = "mock_only"

    note = (
        "rating 来自高德(部分类目)；positive_ratio_proxy/review_count_proxy/sentiment_label "
        "含演示用确定性 mock，非真实点评条数。"
    )

    return {
        "gaode": gaode,
        "mock_baseline": mock,
        "for_weights": {
            "star_for_rank": blend_star,
            "positive_ratio_proxy": pos,
            "review_count_proxy": mock.get("review_count_proxy", 100),
            "sentiment_label": mock.get("sentiment_label", "中性"),
        },
        "source": source,
        "_note": note,
    }


def extract_photo_urls(poi_raw: dict[str, Any], *, limit: int = 3) -> list[str]:
    """
    高德 place/text 在 extensions=all 时可能返回 photos（文档称部分为 JSON 字符串）。
    只抽取 http(s) 链接，最多 limit 条，便于 Agent 在 Markdown 里插图。
    """
    raw = poi_raw.get("photos")
    if raw is None:
        return []
    arr: list[Any]
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s in ("[]", "{}"):
            return []
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return []
        arr = parsed if isinstance(parsed, list) else []
    elif isinstance(raw, list):
        arr = raw
    else:
        return []
    urls: list[str] = []
    for ph in arr:
        if not isinstance(ph, dict):
            continue
        u = ph.get("url")
        if isinstance(u, str) and u.startswith(("http://", "https://")):
            urls.append(u)
        if len(urls) >= limit:
            break
    return urls


def enrich_pois_from_search(
    pois_raw: list[dict[str, Any]],
    *,
    city: str,
    attach_mock: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in pois_raw:
        loc = (p.get("location") or "").split(",")
        lng = float(loc[0]) if len(loc) > 1 else None
        lat = float(loc[1]) if len(loc) > 1 else None
        pid = p.get("id")
        item: dict[str, Any] = {
            "id": pid,
            "name": p.get("name"),
            "type": p.get("type"),
            "address": p.get("address"),
            "location": {"lng": lng, "lat": lat},
            "reputation": build_reputation_for_poi(p, city=city, attach_mock=attach_mock),
        }
        if pid not in (None, ""):
            item["amap_place_url"] = f"https://www.amap.com/place/{pid}"
        photo_urls = extract_photo_urls(p, limit=3)
        if photo_urls:
            item["photo_urls"] = photo_urls
        # 可选：透传少量高德扩展，便于调试（体量可控）
        if p.get("business_area"):
            item["business_area"] = p.get("business_area")
        out.append(item)
    return out
