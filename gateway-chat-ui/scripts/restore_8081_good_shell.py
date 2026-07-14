#!/usr/bin/env python3
"""Restore last known-good 8081 app shell (logo-patched) if a bad rebuild replaced it."""
from pathlib import Path
import shutil

www = Path("/var/www/gateway-chat-ui-app")
html = www / "app.html"
bak_js = www / "assets/app-Cq21YTdI.js.bak-logo"
bak_css = www / "assets/app-DT-JDN92.css.bak-logo"
bak_html = www / "app.html.bak-logo"

js = www / "assets/app-Cq21YTdI.js"
css = www / "assets/app-DT-JDN92.css"

# Prefer current logo-patched files if present; else restore from .bak-logo
if bak_js.exists() and not js.exists():
    shutil.copy2(bak_js, js)
if bak_css.exists() and not css.exists():
    shutil.copy2(bak_css, css)

# rewrite app.html to logo-patched good bundle (keep favicon.jpg if logo present)
good = """<!doctype html>
<html lang=\"zh-CN\">
  <head>
    <meta charset=\"UTF-8\" />
    <link rel=\"icon\" type=\"image/jpeg\" href=\"/favicon.jpg\" />
    <meta
      name=\"viewport\"
      content=\"width=device-width, initial-scale=1.0, viewport-fit=cover, maximum-scale=1.0, user-scalable=no\"
    />
    <meta name=\"apple-mobile-web-app-capable\" content=\"yes\" />
    <meta name=\"theme-color\" content=\"#ffc300\" />
    <title>小星</title>
    <script type=\"module\" crossorigin src=\"/assets/app-Cq21YTdI.js\"></script>
    <link rel=\"stylesheet\" crossorigin href=\"/assets/app-DT-JDN92.css\">
  </head>
  <body>
    <div id=\"root\"></div>
  </body>
</html>
"""
# Ensure logo patch still on JS
s = js.read_text(encoding="utf-8")
if "xiaoxing-logo.jpg" not in s and bak_js.exists():
    shutil.copy2(bak_js, js)
    s = js.read_text(encoding="utf-8")
if "xiaoxing-logo.jpg" not in s:
    old = '(0,P.jsx)(`span`,{className:`mobile-logo-icon`,"aria-hidden":!0,children:`星`})'
    new = '(0,P.jsx)(`img`,{className:`mobile-logo-icon`,src:`/xiaoxing-logo.jpg`,alt:``,width:28,height:28,decoding:`async`})'
    if old in s:
        js.write_text(s.replace(old, new, 1), encoding="utf-8")
        print("re-applied logo js patch")

c = css.read_text(encoding="utf-8")
if "object-fit:contain" not in c and bak_css.exists():
    shutil.copy2(bak_css, css)
    c = css.read_text(encoding="utf-8")
if "object-fit:contain" not in c:
    old_css = (
        ".mobile-logo-icon{background:var(--brand);width:28px;height:28px;"
        "color:var(--brand-ink);border-radius:8px;justify-content:center;"
        "align-items:center;font-size:.85rem;font-weight:700;display:inline-flex}"
    )
    new_css = (
        ".mobile-logo-icon{width:32px;height:32px;border-radius:50%;"
        "object-fit:contain;background:transparent;display:block;flex-shrink:0}"
    )
    if old_css in c:
        css.write_text(c.replace(old_css, new_css, 1), encoding="utf-8")
        print("re-applied logo css patch")

html.write_text(good, encoding="utf-8")
print("restored app.html -> app-Cq21YTdI.js")
print("logo in js", "xiaoxing-logo.jpg" in js.read_text(encoding="utf-8"))
