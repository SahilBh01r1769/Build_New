"""Read a small set of project facts before attempting setup."""

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib


IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".next"}
MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml"}


@dataclass(frozen=True)
class ProjectInfo:
    path: Path
    kind: str
    framework: str
    install: tuple[str, ...]
    launch: tuple[str, ...] | None
    observations: tuple[str, ...]
    needs_env: tuple[str, ...]
    runtime_issue: str | None = None


def _version(executable: str) -> str:
    path = shutil.which(executable)
    if not path:
        return f"{executable}: unavailable"
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
        return f"{executable}: {(result.stdout or result.stderr).strip().splitlines()[0]}"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return f"{executable}: present (version unavailable)"


def discover_components(root: Path) -> list[Path]:
    """Find nearby runnable directories without descending into dependencies or examples."""
    found: list[Path] = []
    for directory, children, files in os.walk(root):
        path = Path(directory)
        depth = len(path.relative_to(root).parts)
        children[:] = sorted(child for child in children
                             if child not in IGNORED_DIRS and not child.startswith(".")) if depth < 3 else []
        if depth and MANIFESTS.intersection(files):
            found.append(path)
            children[:] = []
    return found


def _minimum_version(requirement: str) -> tuple[int, int] | None:
    """Handle a simple lower bound; complex version expressions remain the user's choice."""
    if "||" in requirement:
        return None
    match = re.match(r"\s*>=\s*(\d+)(?:\.(\d+))?", requirement)
    return (int(match[1]), int(match[2] or 0)) if match else None


def inspect_project(path: Path) -> ProjectInfo:
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"Project folder does not exist: {path}")

    observations: list[str] = []
    example = path / ".env.example"
    needs_env = tuple(
        line.split("=", 1)[0].strip()
        for line in example.read_text(errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    ) if example.is_file() else ()
    if needs_env:
        observations.append(f"Environment example lists: {', '.join(needs_env)}")

    package = path / "package.json"
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError(f"Cannot read package.json: {exc}") from exc
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict):
            raise ValueError("package.json scripts must be an object")
        if (path / "pnpm-lock.yaml").exists() or (path / "yarn.lock").exists():
            observations.append("Non-npm lockfile detected; this setup path is not supported yet.")
            install = ()
            launch = None
        else:
            install = ("npm", "ci") if (path / "package-lock.json").exists() else ("npm", "install")
            script = next((name for name in ("dev", "start", "serve") if name in scripts), None)
            launch = ("npm", "run", script) if script else None
        observations.extend([_version("node"), _version("npm")])
        engines = data.get("engines")
        required = _minimum_version(str(engines.get("node", ""))) if isinstance(engines, dict) else None
        detected = re.search(r"\bv?(\d+)\.(\d+)", observations[-2])
        issue = None
        if required and detected and (int(detected[1]), int(detected[2])) < required:
            issue = (f"This project requires Node {required[0]}.{required[1]} or later; detected "
                     f"Node {detected[1]}.{detected[2]}. Install a compatible runtime and continue setup.")
        if not launch:
            observations.append("No supported start script found (dev, start or serve).")
        return ProjectInfo(path, "node", "Node web", install, launch, tuple(observations), needs_env, issue)

    requirements = path / "requirements.txt"
    pyproject = path / "pyproject.toml"
    if requirements.is_file() or pyproject.is_file():
        dependencies = ""
        issue = None
        if requirements.is_file():
            dependencies += requirements.read_text(errors="replace").lower()
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError(f"Cannot read pyproject.toml: {exc}") from exc
            dependencies += str(data.get("project", {}).get("dependencies", [])).lower()
            required = _minimum_version(str(data.get("project", {}).get("requires-python", "")))
            if required and sys.version_info[:2] < required:
                issue = (f"This project requires Python {required[0]}.{required[1]} or later; detected "
                         f"Python {sys.version_info.major}.{sys.version_info.minor}. "
                         "Install a compatible runtime and continue setup.")
        framework = next((name for name in ("streamlit", "fastapi", "flask", "django") if name in dependencies), "Python web")
        install = ("pip", "install", "-r", "requirements.txt") if requirements.is_file() else ("pip", "install", "-e", ".")
        launch = None
        if framework == "django" and (path / "manage.py").is_file():
            launch = ("python", "manage.py", "runserver", "127.0.0.1:8000")
        elif framework == "streamlit":
            entry = next((name for name in ("app.py", "main.py", "streamlit_app.py") if (path / name).is_file()), None)
            if entry:
                launch = ("streamlit", "run", entry, "--server.address", "127.0.0.1")
        elif framework == "flask":
            entry = next((name for name in ("app.py", "main.py") if (path / name).is_file()), None)
            if entry:
                launch = ("flask", "--app", entry, "run", "--host", "127.0.0.1")
        elif framework == "fastapi":
            entry = next((name for name in ("main.py", "app.py", "app/main.py", "src/api/main.py")
                          if (path / name).is_file()), None)
            if entry:
                launch = ("uvicorn", f"{entry[:-3].replace('/', '.')}:app", "--host", "127.0.0.1")
        observations.append(_version("python"))
        if not launch:
            observations.append("Could not determine an entry point from common files.")
        return ProjectInfo(path, "python", framework, install, launch, tuple(observations), needs_env, issue)

    components = discover_components(path)
    if len(components) == 1:
        info = inspect_project(components[0])
        return replace(info, observations=(f"Found project in {components[0].relative_to(path)}/.",
                                           *info.observations))
    if components:
        names = ", ".join(str(component.relative_to(path)) for component in components[:8])
        return ProjectInfo(path, "unknown", "Multiple components", (), None,
                           (f"Found components: {names}. Choose the folder to run and try again.",), needs_env)
    return ProjectInfo(path, "unknown", "Unknown", (), None,
                       ("No supported package.json, requirements.txt or pyproject.toml found.",), needs_env)
