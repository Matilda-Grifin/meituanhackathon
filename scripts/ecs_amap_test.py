#!/usr/bin/env python3
import json
import os
import sys
sys.path.insert(0, "/root/meituan-lifecare-agent")
os.chdir("/root/meituan-lifecare-agent")

from lifecare.clients.amap import search_poi_text

cases = [
    ("上海 热门景点 特色餐饮", "上海", 10),
    ("上海 景点", "上海", 10),
    ("上海 餐厅", "上海", 8),
]
for kw, city, lim in cases:
    r = search_poi_text(kw, city, limit=lim)
    print("---", kw)
    print(json.dumps({"ok": r.get("ok"), "error": r.get("error"), "raw_status": r.get("raw_status"), "n": len(r.get("pois") or [])}, ensure_ascii=False))
