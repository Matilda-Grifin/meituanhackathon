#!/usr/bin/env python3
"""路演 PPT：手机屏截图 + 架构图 + PptxGenJS 生成"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MOCK_HTML = REPO / "ui-redesign" / "app-mocks" / "app-v1-meituan.html"
PITCH = ROOT / "pitch-deck"
ASSETS = PITCH / "assets"
OUT = PITCH / "lifecare-finals-pitch-v2.pptx"

SCENES = [
    ("intake", "01-intake.png"),
    ("plan", "02-plan.png"),
    ("stream", "03-stream.png"),
    ("image", "04-image.png"),
]


def capture_screenshots() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    if not MOCK_HTML.is_file():
        return
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright missing; keep existing assets/")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(MOCK_HTML.as_uri())
        page.wait_for_timeout(600)
        for scene, fname in SCENES:
            page.click(f'[data-scene="{scene}"]')
            page.wait_for_timeout(400)
            # 只截手机屏，去掉 dev-panel，PPT 里可以放得更大
            page.locator(".phone-screen").screenshot(path=str(ASSETS / fname))
        browser.close()
    print("screenshots ok (.phone-screen)")


def generate_architecture() -> None:
    script = PITCH / "generate_arch_image.py"
    if script.is_file():
        subprocess.check_call([sys.executable, str(script)], cwd=str(PITCH))


def build_deck() -> None:
    subprocess.check_call(["npm", "install"], cwd=str(PITCH), shell=True)
    env = os.environ.copy()
    env["PPT_OUT"] = OUT.name
    subprocess.check_call(["node", "build_deck.mjs"], cwd=str(PITCH), env=env)
    print(f"saved {OUT}")


def main() -> None:
    capture_screenshots()
    generate_architecture()
    build_deck()


if __name__ == "__main__":
    main()
