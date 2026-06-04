#!/usr/bin/env python3
"""Find sessions with 3+ visible user turns (post-plan follow-up evidence)."""
import json
from pathlib import Path

base = Path("/root/.openclaw/agents/main/sessions")
hits = []
for p in base.glob("*.jsonl"):
    if ".trajectory." in p.name:
        continue
    visible = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        m = o.get("message", o)
        if m.get("role") != "user":
            continue
        texts = []
        for c in m.get("content", []):
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
        t = "\n".join(texts)
        if "[位置上下文]" in t or "Sender (untrusted metadata)" in t:
            continue
        visible.append(t.strip()[:80])
    if len(visible) >= 3:
        hits.append((p.name, len(visible), visible))
print(f"sessions_with_3plus_visible_user={len(hits)}")
for name, n, msgs in hits[:10]:
    print("\n===", name, "n=", n)
    for i, m in enumerate(msgs, 1):
        print(f"  {i}. {m}")
