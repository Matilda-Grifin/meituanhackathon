"""OpenAI-compatible LLM client for user simulator and judge."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_EVAL_USAGE_LOG: Path | None = None


def eval_usage_log_path() -> Path:
    global _EVAL_USAGE_LOG
    if _EVAL_USAGE_LOG is not None:
        return _EVAL_USAGE_LOG
    ws = Path(os.environ.get("OPENCLAW_WORKSPACE", Path.home() / ".openclaw" / "workspace")).expanduser()
    _EVAL_USAGE_LOG = ws / "logs" / "eval-llm-usage.jsonl"
    return _EVAL_USAGE_LOG


def normalize_usage(u: dict | None) -> dict[str, int]:
    u = u or {}
    inp = int(u.get("prompt_tokens") or u.get("input") or u.get("input_tokens") or 0)
    out = int(u.get("completion_tokens") or u.get("output") or u.get("output_tokens") or 0)
    total = int(u.get("total_tokens") or u.get("total") or inp + out)
    reas = int(u.get("reasoning_tokens") or u.get("reasoningTokens") or 0)
    cache = int(u.get("cache_read_tokens") or u.get("cacheRead") or 0)
    return {"input": inp, "output": out, "total": total, "reasoning": reas, "cacheRead": cache}


def merge_usage(acc: dict[str, Any], usage: dict | None, *, model: str = "") -> dict[str, Any]:
    u = normalize_usage(usage)
    if not any(u.values()):
        return acc
    for k in ("input", "output", "total", "reasoning", "cacheRead"):
        acc[k] = int(acc.get(k) or 0) + u[k]
    if model:
        acc["model"] = model
    return acc


def append_eval_usage(
    *,
    role: str,
    model: str,
    usage: dict | None,
    session_id: str = "",
    task_id: str = "",
    batch: str = "",
) -> None:
    u = normalize_usage(usage)
    if not any(u.values()):
        return
    path = eval_usage_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": int(time.time() * 1000),
        "role": role,
        "model": model,
        "usage": u,
        "session_id": session_id or None,
        "task_id": task_id or None,
        "batch": batch or None,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _env_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    out: list[Path] = []
    for parent in here.parents:
        if (parent / "run_mcp.py").is_file():
            out.append(parent / ".env")
            break
    out.extend(
        [
            Path("/root/meituan-lifecare-agent/.env"),
            here.parents[3] / ".env" if len(here.parents) > 3 else Path(),
        ]
    )
    seen: set[str] = set()
    unique: list[Path] = []
    for p in out:
        key = str(p)
        if key in seen or not str(p):
            continue
        seen.add(key)
        unique.append(p)
    return unique


def load_repo_env() -> None:
    for env_path in _env_candidates():
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip().strip("\r")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\r").strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
        return


def _proxy_url() -> str | None:
    return os.environ.get("OVERSEAS_PROXY_HTTPS", "").strip() or None


def resolve_model_env(env_key: str, default: str) -> str:
    return os.environ.get(env_key, default).strip() or default


def _openrouter_config(model: str) -> tuple[str, str, dict[str, str] | None]:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://meituan-hackathon.local",
        "X-Title": "meituan-lifecare-vitabench-eval",
    }
    proxy = _proxy_url()
    return "https://openrouter.ai/api/v1/chat/completions", key, headers if not proxy else headers


def _dashscope_config(model: str) -> tuple[str, str, dict[str, str]]:
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("qwen_api_key", "")
    key = key.strip()
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY / qwen_api_key missing")
    return (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        key,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )


def _deepseek_config(model: str) -> tuple[str, str, dict[str, str]]:
    key = os.environ.get("deepseek_api_key", "").strip()
    if not key:
        raise RuntimeError("deepseek_api_key missing")
    return (
        "https://api.deepseek.com/chat/completions",
        key,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )


def resolve_endpoint(model_spec: str) -> tuple[str, dict[str, str], str]:
    load_repo_env()
    if model_spec in ("user", "user_llm"):
        model_spec = resolve_model_env("user_llm_model", "deepseek/deepseek-v4-flash")
    if model_spec in ("judge", "judge_llm"):
        model_spec = resolve_model_env("judge_llm_model", "openai/gpt-5.5")

    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    headers_or = {"Authorization": f"Bearer {or_key}", "Content-Type": "application/json"}

    if "/" in model_spec and or_key:
        return "https://openrouter.ai/api/v1/chat/completions", headers_or, model_spec

    if model_spec.startswith("deepseek/") or model_spec == "deepseek-v4-flash":
        url = "https://api.deepseek.com/chat/completions"
        key = os.environ.get("deepseek_api_key", "").strip()
        if not key:
            raise RuntimeError("deepseek_api_key missing for user simulator")
        return url, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, "deepseek-chat"

    url, _, headers = _dashscope_config(model_spec)
    return url, headers, model_spec


def chat_completion(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.6,
    max_tokens: int = 2048,
    timeout_s: int = 120,
    usage_role: str = "",
    session_id: str = "",
    task_id: str = "",
    batch: str = "",
) -> str:
    result = chat_completion_with_usage(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        usage_role=usage_role,
        session_id=session_id,
        task_id=task_id,
        batch=batch,
    )
    return result["text"]


def chat_completion_with_usage(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.6,
    max_tokens: int = 2048,
    timeout_s: int = 120,
    usage_role: str = "",
    session_id: str = "",
    task_id: str = "",
    batch: str = "",
) -> dict[str, Any]:
    url, headers, model_id = resolve_endpoint(model)
    body: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    proxy = _proxy_url()
    if proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        opener = urllib.request.build_opener()
    last_err: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with opener.open(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            choices = payload.get("choices") or []
            if not choices:
                raise RuntimeError(f"LLM empty choices: {payload}")
            text = str(choices[0].get("message", {}).get("content") or "").strip()
            usage = normalize_usage(payload.get("usage"))
            if usage_role:
                append_eval_usage(
                    role=usage_role,
                    model=model_id,
                    usage=usage,
                    session_id=session_id,
                    task_id=task_id,
                    batch=batch,
                )
            return {"text": text, "usage": usage, "model": model_id}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"LLM HTTP {e.code}: {err[:800]}")
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise last_err from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = RuntimeError(f"LLM network: {e}")
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise last_err from e
    raise last_err or RuntimeError("LLM request failed")


def parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        text = m.group(0)
    return json.loads(text)
