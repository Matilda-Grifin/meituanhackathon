"""行程长文 → LLM 抽 JSON → Seedream 信息图。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

_lock = threading.Lock()
_cancel_events: dict[str, threading.Event] = {}


class JobCancelled(Exception):
    pass


def register_job(job_id: str) -> threading.Event:
    ev = threading.Event()
    with _lock:
        _cancel_events[job_id] = ev
    return ev


def cancel_job(job_id: str) -> bool:
    with _lock:
        ev = _cancel_events.get(job_id)
    if ev is None:
        return False
    ev.set()
    return True


def cleanup_job(job_id: str) -> None:
    with _lock:
        _cancel_events.pop(job_id, None)


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise JobCancelled()


def _ark_post(path: str, body: dict, *, timeout: int = 180) -> dict:
    base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    key = os.environ.get("ARK_API_KEY", "")
    if not key:
        raise RuntimeError("ARK_API_KEY missing")
    url = f"{base}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


EXTRACT_SYSTEM = """你是行程信息抽取助手。用户会给你一篇完整的出行规划 Markdown 长文。
请从中提取用于「行程信息图」的精简字段，只输出一个 JSON 对象，不要 markdown 代码块。

JSON 结构：
{
  "title": "方案标题（短）",
  "subtitle": "谁+主题，一行",
  "weather": "天气摘要，如 阴 23-31°C",
  "stops": [
    {"time": "09:00", "place": "岳麓山", "icon": "⛰️", "travel_to_next": "打车40分钟"}
  ],
  "budget": "270-610元/2人",
  "tip": "一条最重要提示，10字内"
}

规则：
- stops 按时间顺序，只保留主要游玩/餐饮锚点（6个以内），place 用2-4字中文
- 省略详细理由、点菜、长 Tips
- 若某字段缺失用合理缩写，不要编造与正文矛盾的地点
"""


def extract_structured(plan_text: str) -> tuple[dict[str, Any], float]:
    model = os.environ.get("ARK_MODEL_NAME", "doubao-seed-2-0-mini-260428")
    t0 = time.perf_counter()
    resp = _ark_post(
        "/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": plan_text},
            ],
            "temperature": 0.2,
            "max_tokens": 1200,
        },
        timeout=120,
    )
    elapsed = time.perf_counter() - t0
    content = resp["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return json.loads(content), elapsed


def build_image_prompt(structured: dict[str, Any]) -> str:
    lines = [
        f"一张竖直行程信息图，主题「{structured.get('title', '一日游')}」。",
        f"副标题：{structured.get('subtitle', '')}。",
        f"左上角天气角标：{structured.get('weather', '')}。",
        "中间为时间轴，从上到下：",
    ]
    for stop in structured.get("stops") or []:
        icon = stop.get("icon") or "📍"
        lines.append(
            f"- {stop.get('time', '')} {icon} {stop.get('place', '')}"
            + (f" → 下一段{stop.get('travel_to_next', '')}" if stop.get("travel_to_next") else "")
        )
    lines.extend(
        [
            f"底部左侧预算：💰 {structured.get('budget', '')}。",
            f"底部右侧提示：📅 {structured.get('tip', '')}。",
            "风格：扁平插画，暖色，圆角卡片，亲子友好，时钟和小汽车图标。",
            "不要长段落，不要详细理由，地点用简体中文短名。画幅 2:3 竖版。",
        ]
    )
    return "\n".join(lines)


def generate_image(prompt: str, *, retries: int = 1) -> tuple[str, float]:
    model = os.environ.get("picture_model", "doubao-seedream-5-0-260128")
    last_err: Exception | None = None
    t0 = time.perf_counter()
    for attempt in range(retries + 1):
        try:
            resp = _ark_post(
                "/images/generations",
                {
                    "model": model,
                    "prompt": prompt,
                    "size": "2K",
                    "response_format": "url",
                    "watermark": False,
                    "sequential_image_generation": "disabled",
                },
                timeout=300,
            )
            data = resp.get("data") or []
            if not data or not data[0].get("url"):
                raise RuntimeError(f"no image url: {json.dumps(resp, ensure_ascii=False)[:400]}")
            return data[0]["url"], time.perf_counter() - t0
        except urllib.error.HTTPError as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5)
                continue
            raise
    raise last_err or RuntimeError("generate_image failed")


def run_pipeline(
    plan_markdown: str,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    _check_cancel(cancel)
    structured, extract_s = extract_structured(plan_markdown)
    _check_cancel(cancel)
    prompt = build_image_prompt(structured)
    image_url, image_s = generate_image(prompt)
    _check_cancel(cancel)
    return {
        "ok": True,
        "image_url": image_url,
        "structured": structured,
        "timing_ms": {
            "extract": int(extract_s * 1000),
            "generate": int(image_s * 1000),
            "total": int((extract_s + image_s) * 1000),
        },
    }
