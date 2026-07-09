from __future__ import annotations

import hashlib
import time
from datetime import date
from typing import Any

import httpx

from lifecare.cache_redis import cache_get_json, cache_set_json
from lifecare.config import get_settings

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AMAP_BASE = "https://restapi.amap.com/v3"

CITY_ADCODE: dict[str, str] = {
    "上海": "310000",
    "上海市": "310000",
    "杭州": "330100",
    "杭州市": "330100",
    "北京": "110000",
    "北京市": "110000",
    "广州": "440100",
    "广州市": "440100",
    "深圳": "440300",
    "深圳市": "440300",
}

# WMO weather interpretation codes (Open-Meteo fallback)
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
    96: "雷暴",
    99: "雷暴",
}


def weather_provider() -> str:
    """amap | openmeteo — 有 AMAP_KEY 时默认高德，可用 WEATHER_PROVIDER 覆盖。"""
    settings = get_settings()
    raw = (settings.weather_provider or "").strip().lower()
    if raw in ("openmeteo", "open-meteo"):
        return "openmeteo"
    if raw in ("amap", "gaode"):
        return "amap"
    if settings.amap_key:
        return "amap"
    if settings.use_open_meteo:
        return "openmeteo"
    return "openmeteo"


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


def _amap_weather_key(adcode: str, forecast_days: int) -> str:
    h = hashlib.sha256(f"{adcode},d{forecast_days}".encode()).hexdigest()[:20]
    return f"lifecare:wx:amap:{h}"


def _geocode_key(city: str) -> str:
    h = hashlib.sha256(city.strip().encode()).hexdigest()[:20]
    return f"lifecare:geocode:{h}"


def _adcode_key(city: str, lat: float | None, lon: float | None) -> str:
    h = hashlib.sha256(f"{city}|{lat}|{lon}".encode()).hexdigest()[:20]
    return f"lifecare:adcode:{h}"


def _combine_day_night_weather(day: str | None, night: str | None) -> str:
    d = (day or "").strip()
    n = (night or "").strip()
    if not d and not n:
        return "未知"
    if not n or d == n:
        return d
    if not d:
        return n
    return f"{d}/{n}"


def _parse_temp(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n else None  # NaN guard


def _amap_get(pathname: str, params: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.amap_key:
        return {"ok": False, "error": "AMAP_KEY 未配置"}

    merged = dict(params)
    merged["key"] = settings.amap_key
    url = f"{AMAP_BASE}{pathname}"

    last_error = "amap request failed"
    with httpx.Client(timeout=15.0) as client:
        for attempt in range(3):
            if attempt:
                time.sleep(0.5 * attempt)
            r = client.get(url, params=merged)
            r.raise_for_status()
            data = r.json()
            if str(data.get("status")) == "1":
                return {"ok": True, "data": data}
            info = str(data.get("info") or "")
            last_error = info or last_error
            if "QPS" not in info and "CUQPS" not in info:
                return {"ok": False, "error": last_error, "infocode": data.get("infocode")}
    return {"ok": False, "error": last_error or "amap QPS limit", "infocode": "QPS"}


def resolve_adcode(
    city: str | None = None,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    name = (city or "").strip()
    ck = _adcode_key(name, latitude, longitude)
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    if name:
        if name in CITY_ADCODE:
            out = {"ok": True, "adcode": CITY_ADCODE[name], "label": name}
            cache_set_json(ck, out, ttl_seconds=86400)
            return out
        short = name.removesuffix("市")
        if short in CITY_ADCODE:
            out = {"ok": True, "adcode": CITY_ADCODE[short], "label": name}
            cache_set_json(ck, out, ttl_seconds=86400)
            return out
        district = _amap_get(
            "/config/district",
            {"keywords": name, "subdistrict": "0", "extensions": "base"},
        )
        if district.get("ok"):
            rows = district["data"].get("districts") or []
            if rows and rows[0].get("adcode"):
                row = rows[0]
                out = {"ok": True, "adcode": row["adcode"], "label": row.get("name") or name}
                cache_set_json(ck, out, ttl_seconds=86400)
                return out

    if latitude is not None and longitude is not None:
        regeo = _amap_get(
            "/geocode/regeo",
            {"location": f"{longitude},{latitude}", "extensions": "base"},
        )
        if regeo.get("ok"):
            comp = (regeo["data"].get("regeocode") or {}).get("addressComponent") or {}
            adcode = comp.get("adcode")
            label = comp.get("city") or comp.get("province") or name
            if adcode:
                out = {"ok": True, "adcode": adcode, "label": label or name}
                cache_set_json(ck, out, ttl_seconds=86400)
                return out

    out = {"ok": False, "error": f"未找到城市 adcode: {name or f'{latitude},{longitude}'}"}
    cache_set_json(ck, out, ttl_seconds=3600)
    return out


def fetch_amap_weather(adcode: str, *, forecast_days: int = 7, city_label: str = "") -> dict[str, Any]:
    settings = get_settings()
    if not settings.amap_key:
        return {"ok": False, "error": "AMAP_KEY 未配置"}

    days = max(1, min(16, int(forecast_days)))
    ck = _amap_weather_key(adcode, days)
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

    live_res = _amap_get("/weather/weatherInfo", {"city": adcode, "extensions": "base"})
    if not live_res.get("ok"):
        return {"ok": False, "error": live_res.get("error") or "amap live weather failed"}

    time.sleep(0.4)

    forecast_res = _amap_get("/weather/weatherInfo", {"city": adcode, "extensions": "all"})
    if not forecast_res.get("ok"):
        return {"ok": False, "error": forecast_res.get("error") or "amap forecast failed"}

    live = (live_res["data"].get("lives") or [{}])[0]
    forecast = (forecast_res["data"].get("forecasts") or [{}])[0]
    casts = (forecast.get("casts") or [])[: min(days, 4)]
    today = date.today().isoformat()

    daily_rows: list[dict[str, Any]] = []
    for row in casts:
        max_t = _parse_temp(row.get("daytemp"))
        min_t = _parse_temp(row.get("nighttemp"))
        daily_rows.append(
            {
                "date": row.get("date"),
                "is_today": row.get("date") == today,
                "weather": _combine_day_night_weather(row.get("dayweather"), row.get("nightweather")),
                "temp_max_c": max_t,
                "temp_min_c": min_t,
                "precipitation_mm": None,
            }
        )

    first = daily_rows[0] if daily_rows else {}
    loc_name = city_label or live.get("city") or forecast.get("city") or ""
    out: dict[str, Any] = {
        "ok": True,
        "provider": "amap",
        "location": {
            "city": loc_name,
            "adcode": adcode,
            "reporttime": live.get("reporttime") or forecast.get("reporttime") or "",
        },
        "forecast_days": len(daily_rows) or days,
        "current_temp_c": _parse_temp(live.get("temperature")),
        "weather": live.get("weather") or first.get("weather") or "未知",
        "today_max_c": first.get("temp_max_c"),
        "today_min_c": first.get("temp_min_c"),
        "daily": daily_rows,
    }
    if days > 4:
        out["note"] = "高德预报最多返回 4 天；如需更长预报可改用 Open-Meteo 兜底。"
    cache_set_json(ck, out, ttl_seconds=1800)
    return out


def geocode_city(city: str) -> dict[str, Any]:
    """Open-Meteo 地理编码（免 Key），将城市名解析为经纬度。"""
    name = (city or "").strip()
    if not name:
        return {"ok": False, "error": "city 为空"}

    ck = _geocode_key(name)
    cached = cache_get_json(ck)
    if cached is not None:
        return cached

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
    """Open-Meteo 兜底：当前天气 + 多天预报；96/99 冰雹码降级为雷暴。"""
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
        "provider": "open-meteo",
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


def fetch_weather(
    *,
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    forecast_days: int = 7,
) -> dict[str, Any]:
    """高德优先，失败再 Open-Meteo 兜底。"""
    settings = get_settings()
    days = max(1, min(16, int(forecast_days)))
    label = (city or "").strip() or settings.default_city
    errors: list[str] = []

    if weather_provider() == "amap":
        geo = resolve_adcode(label if (city or "").strip() else None, latitude=latitude, longitude=longitude)
        if not geo.get("ok") and (city or "").strip():
            geo = resolve_adcode(city)
        if geo.get("ok"):
            result = fetch_amap_weather(
                str(geo["adcode"]),
                forecast_days=days,
                city_label=str(geo.get("label") or label),
            )
            if result.get("ok"):
                return result
            errors.append(f"amap: {result.get('error') or 'unknown'}")
        else:
            errors.append(f"adcode: {geo.get('error')}")

    lat = latitude
    lon = longitude
    om_label = label
    if lat is None or lon is None:
        geo = geocode_city((city or "").strip() or settings.default_city)
        if not geo.get("ok"):
            return {"ok": False, "error": "; ".join(errors + [str(geo.get("error") or "geocode failed")])}
        lat = float(geo["latitude"])
        lon = float(geo["longitude"])
        om_label = str(geo.get("city") or label)
        if geo.get("admin1"):
            om_label = f"{om_label}（{geo['admin1']}）"
    elif (city or "").strip():
        om_label = (city or "").strip()

    try:
        result = fetch_open_meteo(lat, lon, forecast_days=days, city_label=om_label)
        if errors:
            result["fallback_from"] = "; ".join(errors)
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "; ".join(errors + [str(exc)])}


def fetch_weather_for_city(city: str | None, *, forecast_days: int = 7) -> dict[str, Any]:
    """按城市名或默认坐标查询多天天气。"""
    settings = get_settings()
    label = (city or "").strip() or settings.default_city
    data = fetch_weather(city=city, forecast_days=forecast_days)
    if data.get("ok") and not (data.get("location") or {}).get("city"):
        data.setdefault("location", {})["city"] = label
    return data
