#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path("/root/meituan-lifecare-agent")
if not ROOT.is_dir():
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lifecare.clients.weather import fetch_weather_for_city  # noqa: E402

city = sys.argv[1] if len(sys.argv) > 1 else "杭州"
days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
d = fetch_weather_for_city(city, forecast_days=days)
print(json.dumps({"ok": d.get("ok"), "days": len(d.get("daily", [])), "dates": [x["date"] for x in d.get("daily", [])]}, ensure_ascii=False))
