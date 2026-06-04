#!/usr/bin/env python3
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ""
last = ""
for line in open(path, encoding="utf-8"):
    o = json.loads(line)
    m = o.get("message", o)
    if m.get("role") != "assistant":
        continue
    t = "".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
    if t.strip():
        last = t
for ln in last.split("\n"):
    if any(k in ln for k in ("南站", "20:", "16:", "休息", "候车", "站内")):
        print(ln[:220])
print("--- table data rows ---", sum(1 for ln in last.split("\n") if ln.strip().startswith("|") and "---" not in ln))
print("--- ### sections ---", last.count("###"))
