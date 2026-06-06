from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_HARNESS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    path = _HARNESS_DIR / "policy.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_repairs() -> dict[str, Any]:
    path = _HARNESS_DIR / "repairs.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def tool_schemas_path() -> Path:
    return _HARNESS_DIR / "tool_schemas.json"
