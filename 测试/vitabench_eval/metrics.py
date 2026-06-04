"""6.3 north-star metrics helpers."""
from __future__ import annotations

from typing import Any


def score_first_response(trajectory: list[dict], ttft_ms: Any = None) -> dict:
    """Port of score_dimensions._score_first_response for vitabench trajectory."""
    first_asst = next((m for m in trajectory if m.get("role") == "assistant"), None)
    if ttft_ms is None and first_asst:
        ttft_ms = first_asst.get("time_to_first_assistant_text_ms") or first_asst.get(
            "time_to_first_progress_ms"
        )
    has_text = bool((first_asst or {}).get("content", "").strip()) if first_asst else False
    has_tool = bool((first_asst or {}).get("tools")) if first_asst else False
    if ttft_ms is None:
        if has_text or has_tool:
            return {"score": 75, "reason": "progress_no_timing"}
        return {"score": 40, "reason": "no_visible_progress"}
    ms = float(ttft_ms)
    if ms <= 10000:
        return {"score": 100, "reason": f"ttft_ms={int(ms)}"}
    if ms <= 15000:
        return {"score": 70, "reason": f"ttft_ms={int(ms)}"}
    if ms <= 25000:
        return {"score": 40, "reason": f"ttft_ms={int(ms)}"}
    return {"score": 10, "reason": f"ttft_ms={int(ms)}"}
