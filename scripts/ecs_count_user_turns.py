#!/usr/bin/env python3
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
visible_user = 0
for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
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
    if "选择题答案" in t or len(t.strip()) < 200:
        print("USER:", t[:120].replace("\n", " "))
    visible_user += 1
print("visible_user_count=", visible_user)
