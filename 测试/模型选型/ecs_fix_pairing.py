#!/usr/bin/env python3
"""One-shot ECS fix: approve CLI device scopes + disable broken feishu plugin."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

PAIRED = Path("/root/.openclaw/devices/paired.json")
PENDING = Path("/root/.openclaw/devices/pending.json")
FEISHU = Path("/root/.openclaw/npm/node_modules/@openclaw/feishu")
FEISHU_OFF = FEISHU.with_suffix(".disabled")


def main() -> None:
    paired = json.loads(PAIRED.read_text(encoding="utf-8"))
    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    for req in pending.values():
        did = req["deviceId"]
        if did not in paired:
            continue
        scopes = sorted(
            set(
                paired[did].get("scopes", [])
                + req.get("scopes", [])
                + ["operator.read", "operator.write", "operator.pairing"]
            )
        )
        paired[did]["scopes"] = scopes
        paired[did]["approvedScopes"] = scopes
        paired[did]["clientMode"] = "cli"
        tok = paired[did].setdefault("tokens", {}).setdefault("operator", {})
        tok["scopes"] = scopes
    PENDING.write_text("{}\n", encoding="utf-8")
    PAIRED.write_text(json.dumps(paired, indent=2) + "\n", encoding="utf-8")
    print("approved scopes:", paired[list(paired.keys())[0]]["scopes"])
    if FEISHU.is_dir() and not FEISHU_OFF.exists():
        shutil.move(str(FEISHU), str(FEISHU_OFF))
        print("disabled feishu plugin")


if __name__ == "__main__":
    main()
