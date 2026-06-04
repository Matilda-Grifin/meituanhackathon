from __future__ import annotations

from typing import Any

import httpx

from lifecare.cache_redis import cache_get_json, cache_set_json
from lifecare.config import get_settings

AMAP_BASE = "https://restapi.amap.com/v3"


def _ok_payload(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def locate_by_ip(ip: str | None = None) -> dict[str, Any]:
    """高德 IP 定位（城市级为主，部分可带 rectangle）。"""
    settings = get_settings()
    if not settings.amap_key:
        return {"ok": False, "error": "AMAP_KEY 未配置", "source": "ip"}

    ip_clean = (ip or "").strip()
    if ip_clean in ("", "127.0.0.1", "::1", "localhost"):
        ip_clean = ""

    ck = f"lifecare:amap:ip:{ip_clean or 'auto'}"
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    params: dict[str, str] = {"key": settings.amap_key}
    if ip_clean:
        params["ip"] = ip_clean

    with httpx.Client(timeout=12.0) as client:
        r = client.get(f"{AMAP_BASE}/ip", params=params)
        r.raise_for_status()
        data = r.json()

    out: dict[str, Any] = {"ok": False, "source": "ip", "ip": ip_clean or None}
    if str(data.get("status")) == "1":
        rect = data.get("rectangle") or ""
        lng, lat = None, None
        if isinstance(rect, str) and ";" in rect:
            try:
                a, b = rect.split(";")[0].split(","), rect.split(";")[1].split(",")
                lng = (float(a[0]) + float(b[0])) / 2
                lat = (float(a[1]) + float(b[1])) / 2
            except (ValueError, IndexError):
                pass
        out = _ok_payload(
            source="ip",
            ip=ip_clean or None,
            province=str(data.get("province") or ""),
            city=str(data.get("city") or ""),
            adcode=str(data.get("adcode") or ""),
            rectangle=rect if rect else None,
            lng=lng,
            lat=lat,
        )
    else:
        out["error"] = data.get("info") or "ip locate failed"

    cache_set_json(ck, out, ttl_seconds=3600)
    return out


def regeo_location(lng: float, lat: float) -> dict[str, Any]:
    """高德逆地理：区、街道、格式化地址。"""
    settings = get_settings()
    if not settings.amap_key:
        return {"ok": False, "error": "AMAP_KEY 未配置", "source": "regeo"}

    ck = f"lifecare:amap:regeo:{lng:.5f},{lat:.5f}"
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    params = {
        "key": settings.amap_key,
        "location": f"{lng},{lat}",
        "extensions": "all",
        "radius": 200,
    }
    with httpx.Client(timeout=12.0) as client:
        r = client.get(f"{AMAP_BASE}/geocode/regeo", params=params)
        r.raise_for_status()
        data = r.json()

    out: dict[str, Any] = {"ok": False, "source": "regeo", "lng": lng, "lat": lat}
    if str(data.get("status")) == "1":
        rg = data.get("regeocode") or {}
        comp = rg.get("addressComponent") or {}
        street = comp.get("streetNumber") or {}
        street_no = ""
        if isinstance(street, dict):
            street_no = f"{street.get('street') or ''}{street.get('number') or ''}".strip()
        out = _ok_payload(
            source="regeo",
            lng=lng,
            lat=lat,
            formatted_address=str(rg.get("formatted_address") or ""),
            province=str(comp.get("province") or ""),
            city=str(comp.get("city") or "") or str(comp.get("province") or ""),
            district=str(comp.get("district") or ""),
            township=str(comp.get("township") or ""),
            street=street_no,
            adcode=str(comp.get("adcode") or ""),
        )
    else:
        out["error"] = data.get("info") or "regeo failed"

    cache_set_json(ck, out, ttl_seconds=1800)
    return out
