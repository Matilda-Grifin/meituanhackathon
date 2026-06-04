#!/usr/bin/env python3
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/agents/main/sessions/e95d6cc9-090a-49c6-9a5e-76635f437a12.jsonl"
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = o.get("message", o)
        role = m.get("role", "")
        ts = o.get("timestamp", "")
        if role == "user":
            for c in m.get("content", []):
                if c.get("type") == "text":
                    print(f"\n[{ts}] USER: {c.get('text','')[:500]}")
        elif role == "assistant":
            for c in m.get("content", []):
                if c.get("type") == "toolCall":
                    print(f"\n[{ts}] CALL {c.get('name')}: {json.dumps(c.get('arguments'), ensure_ascii=False)[:200]}")
                elif c.get("type") == "text":
                    t = c.get("text", "")
                    if t and len(t) > 20:
                        print(f"\n[{ts}] ASSISTANT: {t[:400]}...")
        elif role == "toolResult":
            txt = ""
            for c in m.get("content", []):
                if c.get("type") == "text":
                    txt = c.get("text", "")
            name = m.get("toolName", "")
            try:
                j = json.loads(txt)
                summary = f"ok={j.get('ok')} error={j.get('error')} pois={len(j.get('pois') or [])}"
            except Exception:
                summary = txt[:250]
            print(f"[{ts}] RESULT {name}: {summary}")
