#!/usr/bin/env python3
"""生成架构图 PNG：优先 HTML 截图（精确），可选 OpenRouter 生图"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PITCH = ROOT / "pitch-deck"
ASSETS = PITCH / "assets"
HTML = ASSETS / "architecture.html"
OUT = ASSETS / "architecture.png"
ENV = ROOT.parent / ".env"


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV.is_file():
        return out
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def screenshot_html() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(HTML.as_uri())
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT), full_page=False)
        browser.close()
    print(f"architecture html screenshot -> {OUT}")


def try_openrouter(env: dict[str, str]) -> bool:
    key = env.get("OPENROUTER_API_KEY")
    model = env.get("picture_model_1", "openai/gpt-image-2")
    if not key:
        return False
    prompt = (
        "Professional tech architecture diagram for AI travel planning product, "
        "16:9 presentation slide, Meituan yellow #ffc300 accent, clean flat design, "
        "Chinese labels: App, OpenClaw Gateway, SOUL, Skills, Harness, MCP Amap Redis, "
        "Seed Lite LLM, layered boxes with arrows, white background, no watermark"
    )
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "size": "2K",
            "output_format": "png",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/images",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        items = data.get("data") or []
        if not items:
            return False
        b64 = items[0].get("b64_json") or items[0].get("image")
        if not b64:
            url = items[0].get("url")
            if url:
                with urllib.request.urlopen(url, timeout=60) as r:
                    OUT.write_bytes(r.read())
                print(f"architecture openrouter url -> {OUT}")
                return True
            return False
        OUT.write_bytes(base64.b64decode(b64))
        print(f"architecture openrouter b64 -> {OUT}")
        return True
    except Exception as e:
        print(f"openrouter skip: {e}")
        return False


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    screenshot_html()
    ai_out = ASSETS / "architecture-ai.png"
    if try_openrouter(load_env()) and OUT.is_file():
        if ai_out.exists():
            ai_out.unlink()
        OUT.rename(ai_out)
        screenshot_html()
        print(f"AI variant saved as {ai_out.name} (slide uses HTML version)")


if __name__ == "__main__":
    main()
