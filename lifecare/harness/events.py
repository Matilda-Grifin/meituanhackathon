from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_event(
    *,
    session_key: str,
    phase: str,
    action: str,
    rule_id: str | None = None,
    tool: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if os.environ.get("LIFECARE_HARNESS_LOG", "1").strip() in ("0", "false", "no"):
        return
    path = _events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_key,
        "phase": phase,
        "action": action,
    }
    if rule_id:
        line["rule_id"] = rule_id
    if tool:
        line["tool"] = tool
    if extra:
        line.update(extra)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _events_path() -> Path:
    raw = os.environ.get("LIFECARE_HARNESS_EVENTS_PATH", "").strip()
    if raw:
        return Path(raw)
    root = Path(__file__).resolve().parent.parent.parent
    return root / "benchmark" / "results" / "harness_events.jsonl"


def _audit_path() -> Path:
    raw = os.environ.get("LIFECARE_HARNESS_AUDIT_PATH", "").strip()
    if raw:
        return Path(raw)
    root = Path(__file__).resolve().parent.parent.parent
    return root / "benchmark" / "results" / "harness_audit.jsonl"


def log_audit(
    *,
    session_key: str,
    action: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if os.environ.get("LIFECARE_HARNESS_LOG", "1").strip() in ("0", "false", "no"):
        return
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_key,
        "action": action,
    }
    if extra:
        line.update(extra)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
