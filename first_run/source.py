"""Resolve a local directory or clone a public repository into a chosen location."""

from pathlib import Path
import os
import subprocess
import threading
import time
from urllib.parse import urlparse


def prepare_source(value: str, destination: str = "", cancelled: threading.Event | None = None) -> Path:
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
        if cancelled and cancelled.is_set():
            raise RuntimeError("Clone cancelled.")
        process = subprocess.Popen(
            ["git", "clone", "--", value, str(target)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=(os.name != "nt"),
        )
        deadline = time.monotonic() + 180
        while True:
            try:
                _, errors = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if (cancelled and cancelled.is_set()) or time.monotonic() > deadline:
                    if os.name != "nt":
                        import signal
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise RuntimeError("Clone cancelled or timed out; check the destination before retrying.")
        if process.returncode:
            raise RuntimeError(errors.strip() or "Git clone failed.")
        return target

    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Project folder does not exist: {path}")
    return path
