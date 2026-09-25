"""Read a small set of project facts before attempting setup."""

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tomllib


@dataclass(frozen=True)
class ProjectInfo:
    path: Path
    kind: str
    framework: str
    install: tuple[str, ...]
    launch: tuple[str, ...] | None
    observations: tuple[str, ...]
    needs_env: tuple[str, ...]


def _version(executable: str) -> str:
    path = shutil.which(executable)
    if not path:
        return f"{executable}: unavailable"
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
        return f"{executable}: {(result.stdout or result.stderr).strip().splitlines()[0]}"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return f"{executable}: present (version unavailable)"


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
            script = next((name for name in ("dev", "start") if name in scripts), None)
            launch = ("npm", "run", script) if script else None
        observations.extend([_version("node"), _version("npm")])
        if not launch:
            observations.append("No supported start script found (dev or start).")
        return ProjectInfo(path, "node", "Node web", install, launch, tuple(observations), needs_env)

    requirements = path / "requirements.txt"
    pyproject = path / "pyproject.toml"
    if requirements.is_file() or pyproject.is_file():
        dependencies = ""
        if requirements.is_file():
            dependencies += requirements.read_text(errors="replace").lower()
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError(f"Cannot read pyproject.toml: {exc}") from exc
            dependencies += str(data.get("project", {}).get("dependencies", [])).lower()
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
            entry = next((name for name in ("main.py", "app.py") if (path / name).is_file()), None)
            if entry:
                launch = ("uvicorn", f"{entry[:-3]}:app", "--host", "127.0.0.1")
        observations.append(_version("python"))
        if not launch:
            observations.append("Could not determine an entry point from common files.")
        return ProjectInfo(path, "python", framework, install, launch, tuple(observations), needs_env)

    return ProjectInfo(path, "unknown", "Unknown", (), None,
                       ("No supported package.json, requirements.txt or pyproject.toml found.",), needs_env)
