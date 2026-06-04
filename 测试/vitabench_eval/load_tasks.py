"""Load 6.3 Task JSON files."""
from __future__ import annotations

import json
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_BENCH = _PKG.parent
_REPO = _BENCH.parent
_DEFAULT_TASKS = _REPO.parent / "待修复" / "模型选型评测" / "data" / "tasks"


def tasks_dir(custom: str | None = None) -> Path:
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (_BENCH / custom)
    env = __import__("os").environ.get("V63_TASKS_DIR", "").strip()
    if env:
        return Path(env)
    if _DEFAULT_TASKS.is_dir():
        return _DEFAULT_TASKS
    return _BENCH / "eval_cases" / "vitabench" / "tasks"


def load_task(task_id: str, *, tasks_root: Path | None = None) -> dict:
    root = tasks_root or tasks_dir()
    manifest = root.parent / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for row in data.get("tasks") or []:
            if row.get("id") == task_id:
                path = root.parent / row["file"].replace("tasks/", f"{root.name}/")
                if path.is_file():
                    return json.loads(path.read_text(encoding="utf-8"))
    for p in sorted(root.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        if t.get("id") == task_id:
            return t
    raise FileNotFoundError(f"task {task_id} not under {root}")


def list_task_ids(tasks_root: Path | None = None) -> list[str]:
    root = tasks_root or tasks_dir()
    ids = []
    for p in sorted(root.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        if t.get("id"):
            ids.append(t["id"])
    return ids
