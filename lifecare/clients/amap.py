from __future__ import annotations

import hashlib
from typing import Any

import httpx

from lifecare.cache_redis import cache_get_json, cache_set_json
from lifecare.config import get_settings
from lifecare.reputation import enrich_pois_from_search

AMAP_BASE = "https://restapi.amap.com/v3"


def _poi_cache_key(keywords: str, city: str, extensions: str, attach_mock: bool) -> str:
    h = hashlib.sha256(f"{city}|{keywords}|{extensions}|{int(attach_mock)}".encode()).hexdigest()[:24]
    return f"lifecare:amap:poi:{h}"


def search_poi_text(
    keywords: str,
    city: str,
    *,
    limit: int = 10,
    extensions: str = "all",
    attach_mock_reputation: bool = True,
) -> dict[str, Any]:
    """
    高德关键字搜索（Web 服务 Key）。结果做短 TTL 缓存。

    - extensions=all：可返回 biz_ext 中的 rating/cost（**仅部分类目**，如餐饮/景点/酒店等），
      仍**不含**第三方 App 式逐条评论文本。
    - attach_mock_reputation：为每个 POI 附加确定性 mock 口碑字段，便于全国任意点可测权重。
    """
    settings = get_settings()
    if not settings.amap_key:
        return {"ok": False, "error": "AMAP_KEY 未配置"}

    ext = "all" if (extensions or "").lower() == "all" else "base"
    ck = _poi_cache_key(keywords, city, ext, attach_mock_reputation)
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    params = {
        "key": settings.amap_key,
        "keywords": keywords,
        "city": city,
        "offset": min(limit, 25),
        "page": 1,
        "extensions": ext,
    }
    with httpx.Client(timeout=15.0) as client:
        r = client.get(f"{AMAP_BASE}/place/text", params=params)
        r.raise_for_status()
        data = r.json()

    status = str(data.get("status", ""))
    info = data.get("info") or ""
    out: dict[str, Any] = {
        "ok": False,
        "raw_status": status,
        "extensions": ext,
        "pois": [],
        "_reputation_note": (
            "高德可能返回 rating（非全类目）；for_weights 中含演示用确定性 mock，"
            "用于全国可复现测试，非真实点评条数。"
        ),
    }
    if status != "1":
        out["error"] = info or "amap request failed"
    elif data.get("pois"):
        raw_list = data["pois"][:limit]
        out["ok"] = True
        out["pois"] = enrich_pois_from_search(
            raw_list,
            city=city,
            attach_mock=attach_mock_reputation,
        )
    else:
        # 高德 status=1、info 常为 "OK"，仅表示接口成功；零条 POI 应换更短关键词重试
        out["ok"] = True
        out["count"] = 0
        out["hint"] = "no_pois_for_keywords"
        out["message"] = (
            f"高德未匹配到 POI（关键词：{keywords!r}，城市：{city!r}）。"
            "请改用更短、单一意图的关键词（如「景点」「博物馆」「本帮菜」）分次搜索。"
        )

    cache_set_json(ck, out, ttl_seconds=600)
    return out


def plan_route_driving(
    origin_lng: float, origin_lat: float, dest_lng: float, dest_lat: float
) -> dict[str, Any]:
    """驾车路径规划（简化为一条方案的距离/时间）。"""
    settings = get_settings()
    if not settings.amap_key:
        return {"ok": False, "error": "AMAP_KEY 未配置"}

    origin = f"{origin_lng},{origin_lat}"
    destination = f"{dest_lng},{dest_lat}"
    ck = f"lifecare:amap:route:{origin}:{destination}"
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    params = {
        "key": settings.amap_key,
        "origin": origin,
        "destination": destination,
        "extensions": "base",
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.get(f"{AMAP_BASE}/direction/driving", params=params)
        r.raise_for_status()
        data = r.json()

    out: dict[str, Any] = {"ok": False}
    if data.get("status") == "1" and data.get("route"):
        paths = data["route"].get("paths") or []
        if paths:
            p0 = paths[0]
            out = {
                "ok": True,
                "distance_m": int(p0.get("distance", 0)),
                "duration_s": int(p0.get("duration", 0)),
                "taxi_cost_hint": p0.get("taxi_cost"),
            }
    if not out.get("ok"):
        out["error"] = data.get("info") or "route failed"

    cache_set_json(ck, out, ttl_seconds=900)
    return out


def plan_route_walking(
    origin_lng: float, origin_lat: float, dest_lng: float, dest_lat: float
) -> dict[str, Any]:
    """步行路径规划：距离(米)、时间(秒)。"""
    settings = get_settings()
    if not settings.amap_key:
        return {"ok": False, "error": "AMAP_KEY 未配置"}

    origin = f"{origin_lng},{origin_lat}"
    destination = f"{dest_lng},{dest_lat}"
    ck = f"lifecare:amap:walk:{origin}:{destination}"
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    params = {
        "key": settings.amap_key,
        "origin": origin,
        "destination": destination,
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.get(f"{AMAP_BASE}/direction/walking", params=params)
        r.raise_for_status()
        data = r.json()

    out: dict[str, Any] = {"ok": False, "mode": "walking"}
    if data.get("status") == "1" and data.get("route"):
        paths = data["route"].get("paths") or []
        if paths:
            p0 = paths[0]
            out = {
                "ok": True,
                "mode": "walking",
                "distance_m": int(p0.get("distance", 0)),
                "duration_s": int(p0.get("duration", 0)),
            }
    if not out.get("ok"):
        out["error"] = data.get("info") or "walking route failed"

    cache_set_json(ck, out, ttl_seconds=900)
    return out
