#!/usr/bin/env python3
import json
from pathlib import Path

p = Path("/root/.openclaw/openclaw.json")
d = json.loads(p.read_text(encoding="utf-8"))
gw = d.setdefault("gateway", {})
ui = gw.setdefault("controlUi", {})
ui["allowInsecureAuth"] = True
ui["dangerouslyDisableDeviceAuth"] = True
# preserve allowedOrigins if present
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("patched gateway.controlUi:", json.dumps(ui, indent=2))
