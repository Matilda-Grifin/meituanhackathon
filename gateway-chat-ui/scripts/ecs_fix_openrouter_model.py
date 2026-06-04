#!/usr/bin/env python3
"""Switch default + main session model away from broken OpenRouter slug (404).

Prefer 豆包/火山方舟: see ecs_switch_volcengine_ark.py + run_ecs_switch_from_local_env.py.
"""
from __future__ import annotations

import json
from pathlib import Path

CFG = Path("/root/.openclaw/openclaw.json")
SESS = Path("/root/.openclaw/agents/main/sessions/sessions.json")
# Already listed under agents.defaults.models on this host
FIXED = "openrouter/autostepfun/step-3.5-flash:free"


def main() -> None:
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    ad = cfg.setdefault("agents", {}).setdefault("defaults", {})
    mp = ad.setdefault("model", {})
    old_primary = mp.get("primary")
    mp["primary"] = FIXED
    CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"openclaw.json agents.defaults.model.primary: {old_primary!r} -> {FIXED!r}")

    if SESS.exists():
        store = json.loads(SESS.read_text(encoding="utf-8"))
        key = "agent:main:main"
        if key in store:
            row = store[key]
            row["model"] = "autostepfun/step-3.5-flash:free"
            row["modelProvider"] = "openrouter"
            SESS.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"patched session row {key} model -> openrouter + autostepfun/step-3.5-flash:free")
        else:
            print(f"no {key} in session store; only defaults updated")


if __name__ == "__main__":
    main()
