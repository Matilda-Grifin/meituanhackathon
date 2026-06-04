import json
import os
import urllib.request

proxy = os.environ.get("OVERSEAS_PROXY_HTTPS") or None
print("proxy", (proxy.split("@")[-1] if proxy else "none"))

cases = [
    ("doubao", os.environ["ARK_BASE_URL"] + "/chat/completions", os.environ["ARK_API_KEY"], os.environ["ARK_MODEL_NAME"], None),
    ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", os.environ["qwen_api_key"], os.environ["qwen_model"], None),
    ("deepseek-or", "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"], os.environ["deepseek_model"], proxy),
    ("gemini-or", "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"], os.environ["openrouter_model2"], proxy),
    ("claude-or", "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"], os.environ["openrouter_model3"], proxy),
    ("gpt-or", "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"], os.environ["openrouter_model4"], proxy),
]

passed = 0
for name, url, key, model, px in cases:
    payload = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "reply exactly: OK"}], "max_tokens": 16}
    ).encode()
    handlers = []
    if px:
        handlers.append(urllib.request.ProxyHandler({"http": px, "https": px}))
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=60) as r:
            data = json.load(r)
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or str(choice)[:80]
        print("[OK]", name, model, repr(content)[:80])
        passed += 1
    except Exception as e:
        print("[FAIL]", name, model, e)

print(passed, "/", len(cases), "passed")
raise SystemExit(0 if passed == len(cases) else 1)
