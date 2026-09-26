"""Remember successful local launch routes for later sessions."""

import hashlib
import json
from pathlib import Path


def history_path() -> Path:
    return Path.home() / ".config" / "first-run" / "projects.json"


def installs_path() -> Path:
    return history_path().with_name("installs.json")


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


def save_install(path: Path):
    """Record a completed dependency install, even if launch needs user input."""
    try:
        data = json.loads(installs_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[str(path)] = setup_fingerprint(path)
    target = installs_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(target)


def installed_setup(path: Path, kind: str) -> bool:
    try:
        data = json.loads(installs_path().read_text(encoding="utf-8"))
        if kind == "python":
            present = (path / ".venv").is_dir()
        else:
            package = json.loads((path / "package.json").read_text(encoding="utf-8"))
            has_dependencies = bool(package.get("dependencies") or package.get("devDependencies"))
            present = not has_dependencies or (path / "node_modules").is_dir()
        return present and isinstance(data, dict) and data.get(str(path)) == setup_fingerprint(path)
    except (OSError, ValueError):
        return False


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
