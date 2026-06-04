#!/usr/bin/env python3
"""Smoke-test all 6 evaluation models (local or on ECS)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROXY_DIR = ROOT / "meituan-lifecare-agent" / "overseas-proxy"
sys.path.insert(0, str(PROXY_DIR))

from proxy_helpers import pick_primary_proxy_url, sanitize_proxy_url  # noqa: E402


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise SystemExit(f"missing {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def chat(url: str, key: str, model: str, proxy: str | None) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "reply exactly: OK"}],
            "max_tokens": 16,
        }
    ).encode()
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with opener.open(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("error"):
        raise RuntimeError(data["error"])
    choice = data.get("choices", [{}])[0]
    msg = choice.get("message") or {}
    return msg.get("content") or str(choice)


def main() -> int:
    env = load_env()
    for k, v in env.items():
        os.environ.setdefault(k, v)

    proxy = pick_primary_proxy_url()
    if proxy:
        print(f"proxy: {sanitize_proxy_url(proxy)}")
    else:
        print("proxy: (none)")

    cases = [
        ("doubao", env["ARK_BASE_URL"] + "/chat/completions", env["ARK_API_KEY"], env["ARK_MODEL_NAME"], None),
        ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", env["qwen_api_key"], env["qwen_model"], None),
        ("deepseek-or", "https://openrouter.ai/api/v1/chat/completions", env["OPENROUTER_API_KEY"], env["deepseek_model"], proxy),
        ("gemini-or", "https://openrouter.ai/api/v1/chat/completions", env["OPENROUTER_API_KEY"], env["openrouter_model2"], proxy),
        ("claude-or", "https://openrouter.ai/api/v1/chat/completions", env["OPENROUTER_API_KEY"], env["openrouter_model3"], proxy),
        ("gpt-or", "https://openrouter.ai/api/v1/chat/completions", env["OPENROUTER_API_KEY"], env["openrouter_model4"], proxy),
    ]

    passed = 0
    for name, url, key, model, use_proxy in cases:
        try:
            out = chat(url, key, model, use_proxy)
            print(f"[OK] {name} ({model}): {out!r}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name} ({model}): {e}")

    print(f"\n{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
