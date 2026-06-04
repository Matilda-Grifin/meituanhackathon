#!/usr/bin/env python3
"""Parse OpenClaw session jsonl for debugging."""
import json
import sys

path = sys.argv[1]
user_msgs = []
asst_msgs = []
tools = []

for line in open(path, encoding="utf-8"):
    try:
        o = json.loads(line)
    except json.JSONDecodeError:
        continue
    t = o.get("type", "")
    if t == "message":
        m = o.get("message", {})
        role = m.get("role")
        parts = []
        for b in m.get("content") or []:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "toolCall":
                    tools.append(b.get("name", "?"))
        text = "".join(parts) if parts else (m.get("text") or "")
        if role == "user" and text and "位置上下文" not in text[:40]:
            user_msgs.append(text)
        if role == "assistant" and text:
            asst_msgs.append((len(text), text[:100].replace("\n", " ")))
    if "toolCall" in line:
        for name in ("get_weather", "search_places", "plan_route"):
            if name in line:
                pass

print("=== USER ===")
for u in user_msgs:
    print(f"- ({len(u)} chars) {u[:200]}")
print("=== ASSISTANT ===")
for ln, head in asst_msgs:
    print(f"- [{ln}] {head}")
print("=== TOOL CALLS (order) ===")
for name in tools:
    print(f"- {name}")
print("=== CHECK IMAGE TRIGGER ===")
if asst_msgs:
    longest = max(asst_msgs, key=lambda x: x[0])
    print(f"longest plan: {longest[0]} chars")
    full = ""
    for line in open(path, encoding="utf-8"):
        o = json.loads(line)
        if o.get("type") != "message":
            continue
        m = o.get("message", {})
        if m.get("role") != "assistant":
            continue
        parts = []
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        text = "".join(parts)
        if len(text) > len(full):
            full = text
    print("has 行程速览:", "行程速览" in full or "## 📋" in full)
    print("has budget:", bool(__import__("re").search(r"预算|💰|费用", full)))
    print("had search_places:", any("search_places" in x for x in tools))
    print("intake in plan:", bool(__import__("re").search(r"^\s*1[\.、]", full, re.M)))
