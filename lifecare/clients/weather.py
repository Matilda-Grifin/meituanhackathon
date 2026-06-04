from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import httpx

from lifecare.cache_redis import cache_get_json, cache_set_json
from lifecare.config import get_settings

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes (Open-Meteo)
WMO_LABELS: dict[int, str] = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "小阵雨",
    81: "阵雨",
    82: "大阵雨",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def wmo_label(code: int | float | None) -> str:
    if code is None:
        return "未知"
    try:
        return WMO_LABELS.get(int(code), f"代码{int(code)}")
    except (TypeError, ValueError):
        return "未知"


def _weather_key(lat: float, lon: float, forecast_days: int) -> str:
    h = hashlib.sha256(f"{lat:.4f},{lon:.4f},d{forecast_days}".encode()).hexdigest()[:20]
    return f"lifecare:wx:{h}"


def _geocode_key(city: str) -> str:
    h = hashlib.sha256(city.strip().encode()).hexdigest()[:20]
    return f"lifecare:geocode:{h}"


def geocode_city(city: str) -> dict[str, Any]:
    """Open-Meteo 地理编码（免 Key），将城市名解析为经纬度。"""
    name = (city or "").strip()
    if not name:
        return {"ok": False, "error": "city 为空"}

    settings = get_settings()
    ck = _geocode_key(name)
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    if not settings.use_open_meteo:
        return {"ok": False, "error": "USE_OPEN_METEO 已关闭"}

    params = {"name": name, "count": 5, "language": "zh", "format": "json"}
    with httpx.Client(timeout=15.0) as client:
        r = client.get(GEOCODE_URL, params=params)
        r.raise_for_status()
        data = r.json()

    results = data.get("results") or []
    if not results:
        out = {"ok": False, "error": f"未找到城市: {name}"}
        cache_set_json(ck, out, ttl_seconds=3600)
        return out

    # 优先中国（CN），否则取第一条
    pick = next((x for x in results if x.get("country_code") == "CN"), results[0])
    out = {
        "ok": True,
        "city": pick.get("name") or name,
        "admin1": pick.get("admin1"),
        "country": pick.get("country"),
        "latitude": float(pick["latitude"]),
        "longitude": float(pick["longitude"]),
        "timezone": pick.get("timezone"),
    }
    cache_set_json(ck, out, ttl_seconds=86400)
    return out


def fetch_open_meteo(
    lat: float,
    lon: float,
    *,
    forecast_days: int = 7,
    city_label: str | None = None,
) -> dict[str, Any]:
    """Open-Meteo：当前天气 + 从今天起的连续多日预报（默认 7 天，最多 16 天）。"""
    settings = get_settings()
    if not settings.use_open_meteo:
        return {"ok": False, "error": "USE_OPEN_METEO 已关闭"}

    days = max(1, min(16, int(forecast_days)))

    ck = _weather_key(lat, lon, days)
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum",
        "timezone": "auto",
        "forecast_days": days,
    }
    with httpx.Client(timeout=15.0) as client:
        r = client.get(FORECAST_URL, params=params)
        r.raise_for_status()
        data = r.json()

    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    times: list[str] = list(daily.get("time") or [])
    max_temps: list[Any] = list(daily.get("temperature_2m_max") or [])
    min_temps: list[Any] = list(daily.get("temperature_2m_min") or [])
    codes: list[Any] = list(daily.get("weather_code") or [])
    precip: list[Any] = list(daily.get("precipitation_sum") or [])

    daily_rows: list[dict[str, Any]] = []
    today_s = date.today().isoformat()
    for i, day in enumerate(times):
        code = codes[i] if i < len(codes) else None
        row = {
            "date": day,
            "is_today": day == today_s,
            "weather_code": code,
            "weather": wmo_label(code),
            "temp_max_c": max_temps[i] if i < len(max_temps) else None,
            "temp_min_c": min_temps[i] if i < len(min_temps) else None,
            "precipitation_mm": precip[i] if i < len(precip) else None,
        }
        daily_rows.append(row)

    first = daily_rows[0] if daily_rows else {}
    out: dict[str, Any] = {
        "ok": True,
        "location": {
            "city": city_label or "",
            "latitude": lat,
            "longitude": lon,
            "timezone": data.get("timezone"),
        },
        "forecast_days": days,
        "current_temp_c": cur.get("temperature_2m"),
        "weather_code": cur.get("weather_code"),
        "weather": wmo_label(cur.get("weather_code")),
        "today_max_c": first.get("temp_max_c"),
        "today_min_c": first.get("temp_min_c"),
        "daily": daily_rows,
    }
    cache_set_json(ck, out, ttl_seconds=1800)
    return out


def fetch_weather_for_city(city: str | None, *, forecast_days: int = 7) -> dict[str, Any]:
    """按城市名或默认坐标查询多天天气。"""
    settings = get_settings()
    label = (city or "").strip() or settings.default_city

    if (city or "").strip():
        geo = geocode_city(city.strip())
        if not geo.get("ok"):
            return geo
        lat = float(geo["latitude"])
        lon = float(geo["longitude"])
        label = str(geo.get("city") or city)
        if geo.get("admin1"):
            label = f"{label}（{geo['admin1']}）"
    else:
        lat = settings.default_lat
        lon = settings.default_lng

    data = fetch_open_meteo(lat, lon, forecast_days=forecast_days, city_label=label)
    if data.get("ok") and not data.get("location", {}).get("city"):
        data.setdefault("location", {})["city"] = label
    return data
