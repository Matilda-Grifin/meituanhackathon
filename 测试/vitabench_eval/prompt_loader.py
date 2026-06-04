"""Load yaml prompt blocks (chinese: |-)."""
from __future__ import annotations

from pathlib import Path


def load_yaml_prompt(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if "chinese: |-" in raw:
        block = raw.split("chinese: |-", 1)[1]
        if "english:" in block:
            block = block.split("english:", 1)[0]
        return block.strip()
    return raw.strip()
