"""Resolve a local directory or clone a public repository into a chosen location."""

from pathlib import Path
import subprocess
from urllib.parse import urlparse


def prepare_source(value: str, destination: str = "") -> Path:
    value = value.strip()
    if not value:
        raise ValueError("Choose a local folder or enter a repository URL.")

    if value.startswith("https://"):
        url = urlparse(value)
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Enter a plain HTTPS repository URL without credentials or query parameters.")
        if not destination.strip():
            raise ValueError("Choose a destination folder for the repository.")
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise ValueError(f"Destination already exists: {target}")
        if not target.parent.is_dir():
            raise ValueError(f"Destination parent does not exist: {target.parent}")
        completed = subprocess.run(
            ["git", "clone", "--", value, str(target)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "Git clone failed.")
        return target

    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Project folder does not exist: {path}")
    return path
