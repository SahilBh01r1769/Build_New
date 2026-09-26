"""Remember successful local launch routes for later sessions."""

import hashlib
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


def setup_fingerprint(path: Path) -> str:
    """A saved route can skip installation only while its dependency inputs match."""
    digest = hashlib.sha256()
    for name in ("requirements.txt", "pyproject.toml", "package.json", "package-lock.json"):
        manifest = path / name
        if manifest.is_file():
            digest.update(name.encode())
            digest.update(b"\0")
            digest.update(manifest.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def save_project(path: Path, launch: tuple[str, ...]):
    previous = [item for item in recent() if item.get("path") != str(path)]
    previous.insert(0, {"path": str(path), "launch": list(launch),
                        "setup_fingerprint": setup_fingerprint(path)})
    target = history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(previous[:15], indent=2), encoding="utf-8")
    temporary.replace(target)


def saved_launch(path: Path) -> tuple[str, ...] | None:
    for item in recent():
        if item.get("path") == str(path):
            if item.get("setup_fingerprint") != setup_fingerprint(path):
                return None
            launch = item.get("launch")
            if isinstance(launch, list) and all(isinstance(part, str) for part in launch):
                return tuple(launch)
    return None
