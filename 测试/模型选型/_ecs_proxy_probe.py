#!/usr/bin/env python3
"""One-off ECS probe: proxy + user/judge LLM (run via ssh python3 < file)."""
import os
import sys
import time
from pathlib import Path

REPO = Path("/root/meituan-lifecare-agent")
BENCH = REPO / "benchmark"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(BENCH))

# load .env without CRLF issues
for p in (REPO / ".env",):
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip().replace("\r", "")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from vitabench_eval.llm_client import chat_completion, _proxy_url

proxy = _proxy_url()
print("proxy:", (proxy or "NONE")[:50] + "..." if proxy and len(proxy) > 50 else proxy)
user_m = os.environ.get("user_llm_model", "deepseek/deepseek-v4-flash")
judge_m = os.environ.get("judge_llm_model", "openai/gpt-5.5")

for label, model in [("user_sim", user_m), ("judge", judge_m)]:
    t0 = time.time()
    try:
        out = chat_completion(model=model, messages=[{"role": "user", "content": "reply OK only"}], max_tokens=32, timeout_s=90)
        print(f"{label} OK ({time.time()-t0:.1f}s):", out[:60])
    except Exception as e:
        print(f"{label} FAIL ({time.time()-t0:.1f}s):", type(e).__name__, str(e)[:400])
