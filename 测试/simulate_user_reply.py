#!/usr/bin/env python3
"""
模拟用户回复：支持脚本（选择题句式）或 LLM 自由口语（更贴近真实用户）。

环境变量（任选其一，OpenAI 兼容）：
  LLM_API_KEY / ARK_API_KEY
  LLM_BASE_URL / ARK_BASE_URL（可选）
  LLM_MODEL / ARK_MODEL（可选，默认 gpt-4o-mini）
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from intake_simulator import (
    build_simulated_user_reply,
    extract_intake_prompt_excerpt,
    format_user_facts,
    resolve_choices_from_assistant,
)

_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    load_dotenv(_ROOT.parent / ".env")
except ImportError:
    pass


def llm_available() -> bool:
    return bool(os.environ.get("LLM_API_KEY", "").strip() or os.environ.get("ARK_API_KEY", "").strip())


def _llm_config() -> tuple[str, str, str]:
    key = os.environ.get("LLM_API_KEY", "").strip() or os.environ.get("ARK_API_KEY", "").strip()
    base = (
        os.environ.get("LLM_BASE_URL", "").strip()
        or os.environ.get("ARK_BASE_URL", "").strip()
        or "https://api.openai.com/v1"
    )
    model = (
        os.environ.get("LLM_MODEL", "").strip()
        or os.environ.get("ARK_MODEL", "").strip()
        or "gpt-4o-mini"
    )
    return key, base, model


def generate_llm_user_reply(
    *,
    case_user_text: str,
    assistant_text: str,
    intent_hint: str = "",
    user_facts: dict | None = None,
    prior_user_messages: list[str] | None = None,
) -> str:
    key, base, model = _llm_config()
    if not key:
        raise RuntimeError("no LLM_API_KEY or ARK_API_KEY")

    excerpt = extract_intake_prompt_excerpt(assistant_text, max_len=1200)
    prior = "\n".join(f"- {m}" for m in (prior_user_messages or []))

    facts_block = format_user_facts(user_facts or {})
    system = (
        "你在扮演真实用户，与美团本地生活出行管家对话。"
        "请用一两句简短中文回复，不要解释自己是 AI。"
        "若管家出了 A/B/C/D 选择题，请根据下方「用户已知信息」用口语回答对应问题；"
        "可以自然描述（如「我们一共3个人」），不要机械套写「第1题选A」除非选项无法口语表达。"
        "只补充管家正在问的信息；不要编造与已知信息矛盾的内容。"
    )
    user = (
        f"用户最初需求：{case_user_text}\n"
        f"此前用户已说：\n{prior or '（无）'}\n"
        f"用户已知信息（答题依据）：\n{facts_block or intent_hint or '按常理补充槽位'}\n"
        f"管家刚说：\n{excerpt}\n"
        "只输出用户下一条消息正文，不要引号包裹。"
    )
    url = base.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 256,
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        r.raise_for_status()
        data = r.json()
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    content = content.strip().strip('"').strip("「」")
    if not content:
        raise RuntimeError("empty llm user reply")
    return content


def resolve_user_reply(
    spec: dict[str, Any],
    *,
    assistant_text: str,
    case_user_text: str,
    prior_user_messages: list[str] | None = None,
    default_mode: str = "auto",
) -> tuple[str, str]:
    """
    返回 (user_reply, source)  source in script | llm | script_fallback
    """
    mode = (spec.get("reply_mode") or default_mode).lower()
    if mode == "auto":
        mode = "choices" if spec.get("user_facts") else ("llm" if llm_available() else "script")

    if mode == "choices":
        facts = spec.get("user_facts") or {}
        if facts and assistant_text and not spec.get("choices"):
            ch, note = resolve_choices_from_assistant(assistant_text, facts)
            if ch:
                spec["choices"] = ch
                if note:
                    spec["other_note"] = note
        return (
            build_simulated_user_reply(spec, assistant_text=assistant_text),
            "choices_from_facts",
        )

    if mode == "llm":
        try:
            facts = spec.get("user_facts") or {}
            hint = format_user_facts(facts) or spec.get("intent_hint") or spec.get("rationale") or ""
            return (
                generate_llm_user_reply(
                    case_user_text=case_user_text,
                    assistant_text=assistant_text,
                    intent_hint=hint,
                    user_facts=facts,
                    prior_user_messages=prior_user_messages,
                ),
                "llm",
            )
        except Exception:
            if spec.get("user_message") or spec.get("user_facts") or spec.get("choices"):
                return build_simulated_user_reply(spec, assistant_text=assistant_text), "script_fallback"
            raise

    return build_simulated_user_reply(spec, assistant_text=assistant_text), "script"
