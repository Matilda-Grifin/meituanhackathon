#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("/var/www/gateway-chat-ui-app/assets/app-CP3EmMi2.js")
t = p.read_text(encoding="utf-8")
print("len", len(t))
for needle in [
    "chat-welcome",
    "xiaoxing-logo",
    "placeholder",
    "想去哪",
    "想调整",
    "小星",
    "AI路线",
    "你好",
    "app-mobile",
]:
    print(repr(needle), t.find(needle))

print("utf8 你好 bytes", t.encode("utf-8").find("你好".encode("utf-8")))

# look in source tree used for build
src = Path("/tmp/gateway-chat-ui-build/src/App.tsx")
if src.exists():
    s = src.read_text(encoding="utf-8")
    print("src has welcome", "chat-welcome" in s)
    print("src has placeholder new", "跟我说说你想去哪" in s)
    print("src has old placeholder", "有什么想调整的" in s)
else:
    print("no build App.tsx")

# search built chunk for welcome CSS class from any file
for jp in Path("/var/www/gateway-chat-ui-app/assets").glob("*.js"):
    tt = jp.read_text(encoding="utf-8", errors="ignore")
    if "chat-welcome" in tt or "跟我说说" in tt or "xiaoxing-logo.jpg" in tt:
        print("hit in", jp.name, "welcome", "chat-welcome" in tt, "placeholder", "跟我说说" in tt, "logo", "xiaoxing-logo.jpg" in tt)
