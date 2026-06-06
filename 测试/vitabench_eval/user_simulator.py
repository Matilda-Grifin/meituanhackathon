"""User simulator LLM."""
from __future__ import annotations

import json
from pathlib import Path

from vitabench_eval.llm_client import chat_completion, load_repo_env
from vitabench_eval.prompt_loader import load_yaml_prompt

STOP = "###STOP###"
_EMPTY_RETRY_NUDGE = "（请继续以用户身份回复一行；若任务已完成请只输出 ###STOP###）"
_MAX_EMPTY_RETRIES = 2
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "user_simulator_zh.yaml"


def _load_prompt() -> str:
    return load_yaml_prompt(_PROMPT_PATH)


class UserSimulator:
    def __init__(self, task: dict, *, model: str = "user", temperature: float = 0.6):
        load_repo_env()
        self.task = task
        self.model = model
        self.temperature = temperature
        persona = json.dumps(task.get("user_scenario", {}).get("user_profile") or {}, ensure_ascii=False, indent=2)
        instructions = task.get("instructions") or ""
        self.system = _load_prompt().format(persona=persona, instructions=instructions)
        self.history: list[dict[str, str]] = []

    def _complete_user_text(self, messages: list[dict[str, str]]) -> str:
        """Call user LLM; retry on empty; fall back to STOP."""
        for attempt in range(_MAX_EMPTY_RETRIES + 1):
            msgs = list(messages)
            if attempt > 0:
                msgs.append({"role": "user", "content": _EMPTY_RETRY_NUDGE})
            text = (chat_completion(model=self.model, messages=msgs, temperature=self.temperature) or "").strip()
            if text:
                return text
        return STOP

    def first_message(self) -> str:
        msgs = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": "请开始：输出你作为用户的第一条消息（一行）。"},
        ]
        text = self._complete_user_text(msgs)
        self.history.append({"role": "user", "content": text})
        return text

    def respond(self, assistant_text: str) -> str:
        self.history.append({"role": "assistant", "content": assistant_text})
        msgs = [{"role": "system", "content": self.system}] + self.history
        text = self._complete_user_text(msgs)
        self.history.append({"role": "user", "content": text})
        return text

    @staticmethod
    def is_stop(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return True
        return STOP in t

    @staticmethod
    def is_empty(text: str) -> bool:
        return not (text or "").strip()
