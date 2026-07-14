#!/usr/bin/env python3
"""Patch live app-Cq21YTdI.js empty-state welcome (placeholder may already be done)."""
from __future__ import annotations

from pathlib import Path

www = Path("/var/www/gateway-chat-ui-app")
js = www / "assets/app-Cq21YTdI.js"
css = www / "assets/app-DT-JDN92.css"

s = js.read_text(encoding="utf-8")

old_ph = "有什么想调整的？"
new_ph = "跟我说说你想去哪？"
if old_ph in s:
    s = s.replace(old_ph, new_ph, 1)
    print("placeholder replaced")
elif new_ph in s:
    print("placeholder already updated")
else:
    raise SystemExit("placeholder string not found")

found = "return e.map(e=>(0,P.jsx)(v.Fragment,{children:e.node},e.key))"
if "chat-welcome" in s:
    print("welcome already present")
else:
    if found not in s:
        raise SystemExit("items.map return pattern not found")
    welcome = (
        "(0,P.jsx)(`div`,{className:`chat-welcome`,children:["
        "(0,P.jsx)(`img`,{className:`chat-welcome-icon`,src:`/xiaoxing-logo.jpg`,alt:``,width:120,height:120,decoding:`async`}),"
        "(0,P.jsx)(`p`,{className:`chat-welcome-text`,children:["
        "(0,P.jsx)(`span`,{className:`chat-welcome-line`,children:`你好，我是小星`}),"
        "(0,P.jsx)(`span`,{className:`chat-welcome-line`,children:`你的AI路线规划伙伴`})"
        "]})"
        "]})"
    )
    new = "return e.length?" + found[len("return ") :] + ":" + welcome
    s = s.replace(found, new, 1)
    print("welcome empty-state injected")
    print("new head", new[:120], "...")

js.write_text(s, encoding="utf-8")

c = css.read_text(encoding="utf-8")
# make .stream a flex column once
stream_rule_start = ".app.app-mobile .stream{"
i = c.find(stream_rule_start)
if i >= 0:
    j = c.find("}", i)
    rule = c[i : j + 1]
    if "display:flex" not in rule:
        c = c[:i] + stream_rule_start + "display:flex;flex-direction:column;" + c[i + len(stream_rule_start) :]
        print("stream flex enabled")

if "chat-welcome{" not in c and ".chat-welcome" not in c:
    welcome_css = (
        ".app.app-mobile .chat-welcome{flex:1;min-height:100%;display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;gap:1rem;"
        "padding:2rem 1.5rem 4rem;text-align:center;box-sizing:border-box}"
        ".app.app-mobile .chat-welcome-icon{width:120px;height:120px;object-fit:contain;"
        "display:block;user-select:none;pointer-events:none}"
        ".app.app-mobile .chat-welcome-text{margin:0;max-width:none;font-size:1.05rem;"
        "line-height:1.55;font-weight:500;color:var(--ink);text-align:center}"
        ".app.app-mobile .chat-welcome-line{display:block;text-align:center}"
    )
    css.write_text(c + welcome_css, encoding="utf-8")
    print("welcome css appended")
else:
    css.write_text(c, encoding="utf-8")
    print("welcome css already present or stream updated")

t = js.read_text(encoding="utf-8")
print(
    "checks",
    {
        "placeholder": new_ph in t,
        "old_ph_gone": old_ph not in t,
        "welcome": "chat-welcome" in t,
        "greeting": "你好呀，我是小星" in t,
        "logo": "xiaoxing-logo.jpg" in t,
    },
)
