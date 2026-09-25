"""Remember successful local launch routes for later sessions."""

import json
from pathlib import Path


def history_path() -> Path:
    return Path.home() / ".config" / "first-run" / "projects.json"


def recent() -> list[dict]:
    try:
        data = json.loads(history_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_project(path: Path, launch: tuple[str, ...]):
    previous = [item for item in recent() if item.get("path") != str(path)]
    previous.insert(0, {"path": str(path), "launch": list(launch)})
    target = history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(previous[:15], indent=2), encoding="utf-8")
    temporary.replace(target)


def saved_launch(path: Path) -> tuple[str, ...] | None:
    for item in recent():
        if item.get("path") == str(path):
            launch = item.get("launch")
            if isinstance(launch, list) and all(isinstance(part, str) for part in launch):
                return tuple(launch)
    return None
