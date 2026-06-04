"""Optional JSONL logging for MCP tool invocations (duration only; no secrets)."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:  # Python < 3.11
    UTC = timezone.utc
from pathlib import Path
from typing import Any, Iterator

_LOG_ENV = "LIFECARE_MCP_TOOL_LOG"


def _default_log_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    out = root / "测试" / "results"
    if not out.parent.is_dir():
        out = root / "benchmark" / "results"
    out.mkdir(parents=True, exist_ok=True)
    return out / "mcp_tool_calls.jsonl"


def _log_path() -> Path:
    custom = os.environ.get("LIFECARE_MCP_TOOL_LOG_PATH", "").strip()
    return Path(custom) if custom else _default_log_path()


def logging_enabled() -> bool:
    """默认开启；设 LIFECARE_MCP_TOOL_LOG=0 / false / off 关闭。"""
    v = os.environ.get(_LOG_ENV, "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


@contextmanager
def tool_span(
    tool_name: str,
    extra: dict[str, Any] | None = None,
    result_holder: dict[str, Any] | None = None,
) -> Iterator[None]:
    if not logging_enabled():
        yield
        return
    t0 = time.perf_counter()
    err: str | None = None
    try:
        yield
    except BaseException as e:
        err = f"{type(e).__name__}:{e}"
        raise
    finally:
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        line = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": tool_name,
            "duration_ms": dt_ms,
            "ok": err is None,
            "error": err,
        }
        if extra:
            line["extra"] = extra
        if result_holder and result_holder.get("result") is not None:
            preview = str(result_holder["result"])
            line["result_preview"] = preview[:4000]
        path = _log_path()
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass
