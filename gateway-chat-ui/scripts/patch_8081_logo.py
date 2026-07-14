#!/usr/bin/env python3
"""One-shot patch: replace live 8081 text logo「星」with /xiaoxing-logo.jpg."""
from __future__ import annotations

from pathlib import Path

www = Path("/var/www/gateway-chat-ui-app")
js = www / "assets/app-Cq21YTdI.js"
css = www / "assets/app-DT-JDN92.css"
html = www / "app.html"

for p in (js, css, html):
    bak = p.with_suffix(p.suffix + ".bak-logo")
    if not bak.exists():
        bak.write_bytes(p.read_bytes())

s = js.read_text(encoding="utf-8")
old = '(0,P.jsx)(`span`,{className:`mobile-logo-icon`,"aria-hidden":!0,children:`星`})'
new = (
    '(0,P.jsx)(`img`,{className:`mobile-logo-icon`,'
    "src:`/xiaoxing-logo.jpg`,alt:``,width:28,height:28,decoding:`async`})"
)
if old not in s:
    raise SystemExit("JS logo pattern not found")
js.write_text(s.replace(old, new, 1), encoding="utf-8")
print("js: replaced logo span -> img")

c = css.read_text(encoding="utf-8")
old_css = (
    ".mobile-logo-icon{background:var(--brand);width:28px;height:28px;"
    "color:var(--brand-ink);border-radius:8px;justify-content:center;"
    "align-items:center;font-size:.85rem;font-weight:700;display:inline-flex}"
)
new_css = (
    ".mobile-logo-icon{width:32px;height:32px;border-radius:50%;"
    "object-fit:contain;background:transparent;display:block;flex-shrink:0}"
)
if old_css not in c:
    raise SystemExit("CSS logo rule not found")
css.write_text(c.replace(old_css, new_css, 1), encoding="utf-8")
print("css: updated .mobile-logo-icon")

h = html.read_text(encoding="utf-8")
old_icon = '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />'
new_icon = '<link rel="icon" type="image/jpeg" href="/favicon.jpg" />'
if old_icon not in h:
    raise SystemExit("favicon link not found")
html.write_text(h.replace(old_icon, new_icon, 1), encoding="utf-8")
print("html: favicon -> jpg")

assert (www / "xiaoxing-logo.jpg").is_file(), "missing logo file"
assert (www / "favicon.jpg").is_file(), "missing favicon"
assert new in js.read_text(encoding="utf-8")
print("ok", (www / "xiaoxing-logo.jpg").stat().st_size)
