#!/usr/bin/env python3
"""Create agent:main:main in local session store (no gateway WS). Safe if key missing."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

STORE = Path("/root/.openclaw/agents/main/sessions/sessions.json")
SESSION_DIR = Path("/root/.openclaw/agents/main/sessions")
KEY = "agent:main:main"


def main() -> None:
    data = json.loads(STORE.read_text(encoding="utf-8"))
    if KEY in data:
        print(f"exists: {KEY}")
        return

    sample_jsonl = next(SESSION_DIR.glob("*.jsonl"), None)
    version = 1
    if sample_jsonl:
        first = sample_jsonl.read_text(encoding="utf-8").splitlines()[0]
        h = json.loads(first)
        version = int(h.get("version", 1))

    sid = str(uuid.uuid4())
    now = int(time.time() * 1000)
    jsonl = SESSION_DIR / f"{sid}.jsonl"
    header = {
        "type": "session",
        "version": version,
        "id": sid,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cwd": "/root",
    }
    jsonl.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")

    data[KEY] = {
        "sessionId": sid,
        "updatedAt": now,
        "systemSent": False,
        "abortedLastRun": False,
        "chatType": "direct",
        "sessionFile": str(jsonl),
        "label": "web-judge",
    }
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"created: {KEY} sessionId={sid}")


if __name__ == "__main__":
    main()
