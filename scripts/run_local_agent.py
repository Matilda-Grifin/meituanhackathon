#!/usr/bin/env python3
"""
本地「小 Agent」：不经过 OpenClaw，用 **同一套 MCP 实现**（直接调 Python）+ 可选 **大模型** 多轮选工具。

- **答辩 / 交付**：赛题若要求 OpenClaw，最终演示仍要用 OpenClaw。
- **自测 / CI**：可用本脚本在无网关环境下跑通「意图 → 工具 → 再总结」闭环。

模式：
  --dry     不调用大模型：规则意图 + 一次搜点（+可选天气/路径），需 AMAP_KEY。
  （默认）  调用 OpenAI 兼容 Chat Completions：需 LLM_API_KEY（及可选 LLM_BASE_URL、LLM_MODEL）。

示例：
  python scripts/run_local_agent.py --dry --message "下午在杭州带娃逛博物馆"
  python scripts/run_local_agent.py --message "帮我安排杭州半日亲子" --max-turns 6

环境变量（LLM 模式）：
  LLM_API_KEY      必填
  LLM_BASE_URL     默认 https://api.openai.com/v1
  LLM_MODEL        默认 gpt-4o-mini
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    load_dotenv(_ROOT.parent / ".env")
except ImportError:
    pass

from lifecare.clients import amap as amap_client
from lifecare.clients import weather as weather_client
from lifecare.config import get_settings

sys.path.insert(0, str(_ROOT / "benchmark"))
from intent_heuristic import classify_intent_heuristic  # noqa: E402


TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "lifecare_search_places",
            "description": "高德关键词搜索 POI（餐厅、景点、商场等），返回含 reputation 的 JSON。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "搜索关键词，可组合如「亲子 博物馆」"},
                    "city": {"type": "string", "description": "城市名，如 杭州"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["keywords", "city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lifecare_get_weather",
            "description": "Open-Meteo 多天预报；city 如杭州；forecast_days 1-16。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                    "forecast_days": {"type": "integer", "default": 7},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lifecare_plan_route",
            "description": "高德驾车：两点间距离(米)、时间(秒)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin_lng": {"type": "number"},
                    "origin_lat": {"type": "number"},
                    "dest_lng": {"type": "number"},
                    "dest_lat": {"type": "number"},
                },
                "required": ["origin_lng", "origin_lat", "dest_lng", "dest_lat"],
            },
        },
    },
]


def _infer_city(text: str, default: str) -> str:
    m = re.search(
        r"(北京|上海|广州|深圳|杭州|南京|成都|重庆|武汉|西安|苏州|青岛|厦门|天津|长沙|郑州|合肥|昆明|哈尔滨|沈阳|长春|南宁|福州|海口|三亚|拉萨|乌鲁木齐|兰州|太原|济南|洛阳|宁波)",
        text,
    )
    return m.group(1) if m else default


def _infer_keywords_dry(text: str) -> str:
    if re.search(r"博物馆|展览|美术馆", text):
        return "博物馆 亲子"
    if re.search(r"朋友|聚会|人", text):
        return "聚餐 商场 娱乐"
    if re.search(r"咖啡|下午茶", text):
        return "精品咖啡"
    return "周末 休闲 餐饮 公园"


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "lifecare_search_places":
        return json.dumps(
            amap_client.search_poi_text(
                arguments["keywords"],
                arguments.get("city") or get_settings().default_city,
                limit=int(arguments.get("limit") or 8),
                extensions="all",
                attach_mock_reputation=True,
            ),
            ensure_ascii=False,
        )
    if name == "lifecare_get_weather":
        days = int(arguments.get("forecast_days") or 7)
        lat = arguments.get("latitude")
        lon = arguments.get("longitude")
        city = arguments.get("city")
        if lat is not None and lon is not None:
            data = weather_client.fetch_open_meteo(
                float(lat),
                float(lon),
                forecast_days=days,
                city_label=str(city or get_settings().default_city),
            )
        else:
            data = weather_client.fetch_weather_for_city(
                str(city) if city else None,
                forecast_days=days,
            )
        return json.dumps(data, ensure_ascii=False)
    if name == "lifecare_plan_route":
        return json.dumps(
            amap_client.plan_route_driving(
                float(arguments["origin_lng"]),
                float(arguments["origin_lat"]),
                float(arguments["dest_lng"]),
                float(arguments["dest_lat"]),
            ),
            ensure_ascii=False,
        )
    return json.dumps({"ok": False, "error": f"unknown tool {name}"}, ensure_ascii=False)


def run_dry(message: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.amap_key:
        raise SystemExit("dry 模式需要 AMAP_KEY（.env）")
    h = classify_intent_heuristic(message)
    city = _infer_city(message, settings.default_city)
    kw = _infer_keywords_dry(message)
    search = amap_client.search_poi_text(kw, city, limit=8, extensions="all", attach_mock_reputation=True)
    w = weather_client.fetch_open_meteo(settings.default_lat, settings.default_lng)
    route_note = None
    if search.get("ok") and search.get("pois") and len(search["pois"]) >= 2:
        a, b = search["pois"][0]["location"], search["pois"][1]["location"]
        if a.get("lng") is not None and b.get("lng") is not None:
            route = amap_client.plan_route_driving(a["lng"], a["lat"], b["lng"], b["lat"])
            route_note = route
    return {
        "mode": "dry",
        "intent_heuristic": h,
        "used_city": city,
        "used_keywords": kw,
        "search": search,
        "weather_default_coords": w,
        "route_first_two_pois": route_note,
    }


def _chat_once(
    client: httpx.Client,
    base: str,
    model: str,
    key: str,
    messages: list[dict],
) -> dict[str, Any]:
    url = base.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "tools": TOOLS_OPENAI,
        "tool_choice": "auto",
        "temperature": 0.3,
    }
    r = client.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def run_llm(message: str, max_turns: int) -> list[dict]:
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        raise SystemExit("请设置环境变量 LLM_API_KEY，或使用 --dry")
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip()
    settings = get_settings()
    system = (
        "你是美团本地生活出行规划助手。根据用户中文需求，**主动调用工具**获取真实数据后再回答。"
        "优先顺序建议：需要室外/时段时先 lifecare_get_weather；再 lifecare_search_places（必须带 city）；"
        "若用户要动线，再 lifecare_plan_route。工具返回为 JSON 字符串请自行阅读。"
        f"用户未说城市时默认城市：{settings.default_city}。"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": message
            + "\n\n[系统注入·规则提示] "
            + json.dumps(classify_intent_heuristic(message), ensure_ascii=False),
        },
    ]
    trace: list[dict[str, Any]] = []
    with httpx.Client(timeout=120.0) as client:
        for turn in range(max_turns):
            data = _chat_once(client, base, model, key, messages)
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            trace.append({"turn": turn, "raw_message": msg})
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                messages.append(msg)
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name")
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                    result = _dispatch_tool(name, args)
                    trace.append({"tool": name, "arguments": args, "result_preview": result[:800]})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": result,
                        }
                    )
                continue
            # 无工具调用，结束
            content = msg.get("content") or ""
            trace.append({"final_reply": content})
            messages.append(msg)
            break
    return trace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", "-m", required=True, help="用户自然语言")
    ap.add_argument("--dry", action="store_true", help="不调大模型，仅规则+MCP")
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("-o", type=Path, default=None, help="写出 JSON 轨迹")
    args = ap.parse_args()

    if args.dry:
        out = run_dry(args.message)
    else:
        out = {"mode": "llm", "trace": run_llm(args.message, args.max_turns)}

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.o:
        args.o.parent.mkdir(parents=True, exist_ok=True)
        args.o.write_text(text, encoding="utf-8")
        print(str(args.o))
    else:
        print(text)


if __name__ == "__main__":
    main()
