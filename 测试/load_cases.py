"""加载评测用例：支持 cases.json（数组）与 cases.jsonl（每行一条）。"""
from __future__ import annotations

import json
from pathlib import Path


def load_eval_cases(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "cases" in data:
        return list(data["cases"])
    raise ValueError(f"unsupported cases file: {path}")
