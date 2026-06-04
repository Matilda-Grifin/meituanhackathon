"""
OpenClaw MCP（stdio）入口：把高德、天气、沙盒封装为工具。

在 openclaw.json 的 mcp.servers 中注册，例如：

  "lifecare": {
    "command": "python",
    "args": ["D:/projects/meituan hackathon/meituan-lifecare-agent/run_mcp.py"],
    "cwd": "D:/projects/meituan hackathon/meituan-lifecare-agent"
  }

注意：OpenClaw 网关会把本进程暴露的工具名加上 MCP 服务器名前缀，形如 **`lifecare__lifecare_get_weather`**
（`lifecare__` + 下方 Python 函数名）。workspace 里的 SOUL / SKILL 已按此前缀书写。

或使用虚拟环境里 python 的绝对路径。

调试：默认会把每条 lifecare_* 的耗时追加到 benchmark/results/mcp_tool_calls.jsonl
（UTC 时间戳）；在 MCP 的 env 中设置 LIFECARE_MCP_TOOL_LOG=0 可关闭。可选 LIFECARE_MCP_TOOL_LOG_PATH 自定义路径。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

# 保证子进程可 import lifecare / sandbox
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lifecare.clients import amap as amap_client
from lifecare.clients import weather as weather_client
from lifecare.config import get_settings
from lifecare.mcp_tool_log import tool_span

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise SystemExit("请先 pip install -r requirements.txt（需要 mcp 包）") from e

mcp = FastMCP(
    "lifecare",
    instructions="本地生活黑客松工具：高德 POI/驾车路线、Open-Meteo 天气、沙盒排队/客流/Mock 下单/打车估算。",
)


def _sandbox_url(path: str) -> str:
    base = get_settings().mock_sandbox_base_url.rstrip("/")
    return f"{base}{path}"


def _sandbox_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> str:
    """
    沙盒 HTTP：不把 502/连不上 变成 MCP 异常，而是返回 JSON，避免模型白等多轮。
    """
    url = _sandbox_url(path)
    try:
        with httpx.Client(timeout=6.0) as client:
            if method.upper() == "GET":
                r = client.get(url, params=params or {})
            else:
                r = client.post(url, params=params or {}, json=json_body)
    except httpx.RequestError as e:
        return json.dumps(
            {
                "ok": False,
                "error": "sandbox_unreachable",
                "detail": str(e),
                "url": url,
                "hint_zh": "连不上沙盒：先在本机起 FastAPI（见项目 README），或检查 MOCK_SANDBOX_BASE_URL。",
            },
            ensure_ascii=False,
        )
    if r.status_code >= 400:
        return json.dumps(
            {
                "ok": False,
                "error": "sandbox_http_error",
                "http_status": r.status_code,
                "url": url,
                "hint_zh": (
                    "沙盒回了错误（常见 502）：9000 上可能不是本项目的 uvicorn，或前面有反代。"
                    "本机请 curl 该 url 自查；不需要沙盒时从 openclaw.json 的 alsoAllow 里移除客流工具。"
                ),
            },
            ensure_ascii=False,
        )
    try:
        return json.dumps(r.json(), ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps(
            {
                "ok": False,
                "error": "sandbox_bad_json",
                "http_status": r.status_code,
                "url": url,
                "hint_zh": "沙盒返回了非 JSON 正文，请确认端口上跑的是 meituan-lifecare-agent/sandbox。",
            },
            ensure_ascii=False,
        )


@mcp.tool()
def lifecare_search_places(
    keywords: str,
    city: str | None = None,
    limit: int = 8,
    extensions: str = "all",
    attach_mock_reputation: bool = True,
) -> str:
    """
    高德关键字搜索 POI（餐饮/景点等），返回 JSON 字符串。

    extensions: 传 `all` 时尽量带高德 biz_ext（部分类目含 rating/cost）；`base` 仅基础字段。
    attach_mock_reputation: 为 true 时每个 POI 附带 `reputation.for_weights`（高德分与确定性 mock 融合），
    便于全国任意 POI 做可复现的「好评率先验」测试；不含真实逐条评论文本。
    """
    holder: dict[str, Any] = {}
    with tool_span(
        "lifecare_search_places",
        {"keywords": (keywords or "")[:80], "city": city or ""},
        result_holder=holder,
    ):
        settings = get_settings()
        c = city or settings.default_city
        data = amap_client.search_poi_text(
            keywords,
            c,
            limit=limit,
            extensions=extensions,
            attach_mock_reputation=attach_mock_reputation,
        )
        out = json.dumps(data, ensure_ascii=False)
        holder["result"] = out
        return out


@mcp.tool()
def lifecare_plan_route(
    origin_lng: float,
    origin_lat: float,
    dest_lng: float,
    dest_lat: float,
) -> str:
    """高德驾车路径规划：距离(米)、时间(秒)、出租车参考价（若有）。"""
    holder: dict[str, Any] = {}
    with tool_span("lifecare_plan_route", {}, result_holder=holder):
        data = amap_client.plan_route_driving(origin_lng, origin_lat, dest_lng, dest_lat)
        out = json.dumps(data, ensure_ascii=False)
        holder["result"] = out
        return out


@mcp.tool()
def lifecare_get_weather(
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    forecast_days: int = 7,
) -> str:
    """
    Open-Meteo 多天天气预报（免 Key，ECS 出网请求）。

    - city：如「杭州」「北京」；与经纬度二选一，都缺省则用 DEFAULT_CITY / DEFAULT_LAT,LNG。
    - forecast_days：从今天起连续天数，1–16（默认 7）。返回 daily[] 含 date、weather、最高/最低温。
    - 查「明天/后天/未来一周」请设足够天数后在 daily 里按 date 取用，勿编造未返回的日期。
    """
    settings = get_settings()
    days = max(1, min(16, int(forecast_days)))
    holder: dict[str, Any] = {}
    with tool_span(
        "lifecare_get_weather",
        {"city": city or "", "forecast_days": days},
        result_holder=holder,
    ):
        if latitude is not None and longitude is not None:
            label = (city or "").strip() or settings.default_city
            data = weather_client.fetch_open_meteo(
                float(latitude),
                float(longitude),
                forecast_days=days,
                city_label=label,
            )
        else:
            data = weather_client.fetch_weather_for_city(city, forecast_days=days)
        out = json.dumps(data, ensure_ascii=False)
        holder["result"] = out
        return out


@mcp.tool()
def lifecare_get_venue_queue(venue_id: str) -> str:
    """沙盒：餐厅排队/是否有位/订座电话。venue_id 可先 lifecare_sandbox_catalog。"""
    with tool_span("lifecare_get_venue_queue", {"venue_id": venue_id}):
        return _sandbox_json("GET", f"/v1/queue/{venue_id}")


@mcp.tool()
def lifecare_get_attraction_crowd(attraction_id: str) -> str:
    """沙盒：景点拥挤度 1-5 与入园等待分钟数。"""
    with tool_span("lifecare_get_attraction_crowd", {"attraction_id": attraction_id}):
        return _sandbox_json("GET", f"/v1/attraction/{attraction_id}/crowd")


@mcp.tool()
def lifecare_sandbox_catalog() -> str:
    """列出沙盒内置餐厅/景点 id，便于规划链路。"""
    with tool_span("lifecare_sandbox_catalog", {}):
        return _sandbox_json("GET", "/v1/catalog")


@mcp.tool()
def lifecare_ride_estimate(distance_m: int = 8000, traffic: str = "normal") -> str:
    """沙盒 Mock：打车费用与时长估算（非真实平台）。"""
    with tool_span(
        "lifecare_ride_estimate",
        {"distance_m": distance_m, "traffic": traffic},
    ):
        return _sandbox_json(
            "GET",
            "/v1/ride/estimate",
            params={"distance_m": distance_m, "traffic": traffic},
        )


@mcp.tool()
def lifecare_submit_mock_order(
    restaurant_id: str,
    party_size: int,
    time_slot: str = "afternoon",
    extras: str = "[]",
    force_failure: str = "",
) -> str:
    """
    沙盒 Mock 下单。extras 为 JSON 数组字符串，如 ["蛋糕","鲜花"]。
    force_failure 可选：full | closed | conflict（赛题异常演示）。
    """
    extras_list: list[Any]
    try:
        extras_list = json.loads(extras) if extras.strip() else []
    except json.JSONDecodeError:
        extras_list = []
    body: dict[str, Any] = {
        "restaurant_id": restaurant_id,
        "party_size": party_size,
        "time_slot": time_slot,
        "extras": extras_list,
    }
    if force_failure:
        body["force_failure"] = force_failure
    with tool_span(
        "lifecare_submit_mock_order",
        {"restaurant_id": restaurant_id, "party_size": party_size},
    ):
        return _sandbox_json("POST", "/v1/order", json_body=body)


@mcp.tool()
def lifecare_inject_sandbox_failure(
    target: str,
    entity_id: str,
    scenario: str,
) -> str:
    """
    演示用：注入沙盒故障。target=restaurant|attraction；
    scenario=none|full|closed|conflict（conflict 主要给订单逻辑语义保留）。
    """
    with tool_span(
        "lifecare_inject_sandbox_failure",
        {"target": target, "entity_id": entity_id, "scenario": scenario},
    ):
        return _sandbox_json(
            "POST",
            "/v1/admin/scenario",
            json_body={"target": target, "id": entity_id, "scenario": scenario},
        )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
