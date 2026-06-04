#!/usr/bin/env python3
"""List session jsonl files with multiple user/assistant turns (for ECS diagnostics)."""
import json
import time
from pathlib import Path

base = Path("/root/.openclaw/agents/main/sessions")
rows = []
for p in base.glob("*.jsonl"):
    if ".trajectory." in p.name:
        continue
    nu = na = 0
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            o = json.loads(line)
            m = o.get("message", o)
            role = m.get("role", "")
            if role == "user":
                nu += 1
            elif role == "assistant":
                na += 1
    except Exception:
        continue
    if nu + na >= 4:
        rows.append((p.stat().st_mtime, p.name, nu, na, p.stat().st_size))
rows.sort(reverse=True)
print("mtime\tfile\tuser\tasst\tbytes")
for mtime, name, nu, na, sz in rows[:12]:
    print(
        time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
        name[:56],
        nu,
        na,
        sz,
        sep="\t",
    )
