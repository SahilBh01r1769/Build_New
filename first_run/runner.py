"""Run local setup steps and keep the launched web process alive."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.error import URLError, HTTPError
from urllib.request import urlopen

from first_run.inspect import ProjectInfo


@dataclass(frozen=True)
class Outcome:
    state: str
    detail: str
    address: str | None = None


class SetupRunner:
    def __init__(self, info: ProjectInfo, report, cancelled: threading.Event):
        self.info = info
        self.report = report
        self.cancelled = cancelled
        self.active: subprocess.Popen | None = None
        self.application: subprocess.Popen | None = None
        self.output: list[str] = []

    def _command(self, args: tuple[str, ...], timeout: int = 600) -> tuple[int, str]:
        self.report("$ " + " ".join(args))
        process = subprocess.Popen(
            args, cwd=self.info.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", start_new_session=(os.name != "nt"),
        )
        self.active = process
        lines: list[str] = []

        def drain():
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line)
                if len(lines) > 200:
                    lines.pop(0)
                self.report(line.rstrip())

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if self.cancelled.is_set() or time.monotonic() > deadline:
                self._stop(process)
                reader.join(timeout=2)
                return -1, "Cancelled or timed out.\n" + "".join(lines[-30:])
            time.sleep(0.1)
        reader.join(timeout=2)
        self.active = None
        return process.returncode, "".join(lines[-30:])

    @staticmethod
    def _stop(process: subprocess.Popen):
        if process.poll() is not None:
            return
        # Child processes inherit the process group on POSIX; stop the group on cancellation.
        if os.name != "nt":
            import signal
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def stop(self):
        self.cancelled.set()
        for process in (self.active, self.application):
            if process:
                self._stop(process)

    def _python(self) -> Path:
        return self.info.path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _environment_values(self) -> tuple[str, ...]:
        example = self.info.path / ".env.example"
        local = self.info.path / ".env"
        if not example.exists():
            return ()
        if not local.exists():
            content = example.read_text(errors="replace")
            local.write_text(content)
            self.report("Created .env from .env.example")
        values = {}
        for line in local.read_text(errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"\'')
        return tuple(key for key in self.info.needs_env if not values.get(key) and not os.environ.get(key))

    def run(self) -> Outcome:
        if not self.info.launch:
            return Outcome("Blocked", "No supported launch command was found. Select a project entry point manually in a later version.")
        missing = self._environment_values()
        if missing:
            return Outcome("Needs input", "Fill these values in the project's .env file, then try again: " + ", ".join(missing))

        if self.info.kind == "python":
            python = self._python()
            if not python.exists():
                code, output = self._command((sys.executable, "-m", "venv", ".venv"), 120)
                if code:
                    return Outcome("Blocked", "Could not create a virtual environment. " + output[-1200:])
            install = (str(python), "-m", *self.info.install)
            launch = ((str(python), *self.info.launch[1:]) if self.info.framework == "django"
                      else (str(python), "-m", *self.info.launch))
        else:
            install = self.info.install
            launch = self.info.launch
        if not install or not launch:
            return Outcome("Blocked", "No supported package manager or launch route was found.")
        code, output = self._command(install)
        if code:
            return Outcome("Blocked", "Dependency installation failed. " + output[-1600:])
        if self.cancelled.is_set():
            return Outcome("Blocked", "Run cancelled.")

        candidates = self._ports()
        occupied = {url for url in candidates if self._responds(url)}
        self.report("$ " + " ".join(launch))
        self.application = subprocess.Popen(
            launch, cwd=self.info.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", start_new_session=(os.name != "nt"),
        )
        app = self.application

        def collect():
            assert app.stdout is not None
            for line in app.stdout:
                self.output.append(line.rstrip())
                if len(self.output) > 100:
                    self.output.pop(0)
                self.report(line.rstrip())

        threading.Thread(target=collect, daemon=True).start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                self.stop()
                return Outcome("Blocked", "Run cancelled.")
            if app.poll() is not None:
                return Outcome("Blocked", "Application exited during startup. " + "\n".join(self.output[-20:])[-1600:])
            found = re.findall(r"https?://(?:localhost|127\.0\.0\.1):\d+", "\n".join(self.output))
            for url in dict.fromkeys([*found, *candidates]):
                if url in occupied:
                    continue
                try:
                    with urlopen(url, timeout=0.7) as response:
                        status = response.status
                    if status < 500 and app.poll() is None:
                        return Outcome("Running", f"HTTP {status} from {url}", url)
                except HTTPError as exc:
                    if exc.code < 500 and app.poll() is None:
                        return Outcome("Running", f"HTTP {exc.code} from {url}", url)
                except (OSError, URLError):
                    pass
            time.sleep(0.5)
        self.stop()
        return Outcome("Blocked", "Application did not respond over HTTP within 30 seconds. " + "\n".join(self.output[-15:])[-1200:])

    @staticmethod
    def _responds(url: str) -> bool:
        try:
            with urlopen(url, timeout=0.3):
                return True
        except HTTPError:
            return True
        except (OSError, URLError):
            return False

    def _ports(self) -> list[str]:
        ports = {"django": (8000,), "fastapi": (8000,), "flask": (5000,),
                 "streamlit": (8501,), "Node web": (3000, 5173, 8080)}
        return [f"http://127.0.0.1:{port}/" for port in ports.get(self.info.framework, ())]
