"""Run local setup steps and keep the launched web process alive."""

from dataclasses import dataclass
import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse
from urllib.request import urlopen

from first_run.inspect import ProjectInfo
from first_run.agent import decide_failure
from first_run.history import installed_setup, save_install, save_project, saved_launch


STARTUP_TIMEOUT = 30


@dataclass(frozen=True)
class Outcome:
    state: str
    detail: str
    address: str | None = None


class SetupRunner:
    def __init__(self, info: ProjectInfo, report, cancelled: threading.Event, api_key: str | None = None):
        self.info = info
        self.report = report
        self.cancelled = cancelled
        self.api_key = api_key
        self.active: subprocess.Popen | None = None
        self.application: subprocess.Popen | None = None
        self.app_reader: threading.Thread | None = None
        self.output: list[str] = []

    def _command(self, args: tuple[str, ...], timeout: int = 600) -> tuple[int, str]:
        self.report("$ " + " ".join(args))
        process = subprocess.Popen(
            args, cwd=self.info.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", start_new_session=(os.name != "nt"),
            env=self._base_env(),
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
                process.stdout.close()
                self.active = None
                return -1, "Cancelled or timed out.\n" + "".join(lines[-30:])
            time.sleep(0.1)
        reader.join(timeout=2)
        process.stdout.close()
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
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False)
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
        if self.app_reader:
            self.app_reader.join(timeout=2)
        if self.application and self.application.stdout:
            self.application.stdout.close()

    def _python(self) -> Path:
        return self.info.path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _environment_values(self) -> tuple[str, ...]:
        example = self.info.path / ".env.example"
        local = self.info.path / ".env"
        if not example.exists():
            return ()
        if not local.exists():
            if self.cancelled.is_set():
                return ()
            content = example.read_text(errors="replace")
            if self.cancelled.is_set():
                return ()
            local.write_text(content)
            self.report("Created .env from .env.example")
        values = {}
        for line in local.read_text(errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"\'')
        child_env = self._base_env()
        return tuple(key for key in self.info.needs_env if not values.get(key) and not child_env.get(key))

    @staticmethod
    def _base_env() -> dict[str, str]:
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        env.pop("FIRST_RUN_MODEL", None)
        return env

    def _app_env(self) -> dict[str, str]:
        env = self._base_env()
        local = self.info.path / ".env"
        if local.is_file():
            for line in local.read_text(errors="replace").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key and key not in env:
                    env[key] = value.strip().strip('"\'')
        return env

    def run(self, reuse: bool = False) -> Outcome:
        if self.cancelled.is_set():
            return Outcome("Blocked", "Run cancelled before setup.")
        if not self.info.launch:
            return Outcome("Blocked", "No supported launch route was found. See Output for the detected project facts; this version starts common root Python web entries or npm dev/start/serve scripts.")
        if self.info.kind == "node" and (not shutil.which("node") or not shutil.which("npm")):
            return Outcome("Needs input", "Node and npm must be installed on the machine. System runtime installation needs your approval outside First Run.")
        missing = self._environment_values()
        if missing:
            return Outcome("Needs input", f"Fill {', '.join(missing)} in {self.info.path / '.env'}, then continue setup.")
        if self.cancelled.is_set():
            return Outcome("Blocked", "Run cancelled before setup.")

        if self.info.kind == "python":
            python = self._python()
            created = not python.exists()
            if not python.exists():
                if self.cancelled.is_set():
                    return Outcome("Blocked", "Run cancelled before setup.")
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
        routes = self._launch_routes(launch)
        previous = saved_launch(self.info.path) if reuse and not (self.info.kind == "python" and created) else None
        ready = installed_setup(self.info.path, self.info.kind)
        if previous not in routes or not ready:
            previous = None
        if previous or (reuse and ready):
            self.report("Using completed setup; dependency installation skipped.")
        else:
            if self.cancelled.is_set():
                return Outcome("Blocked", "Run cancelled before dependency installation.")
            code, output = self._command(install)
            if code:
                if self.cancelled.is_set():
                    return Outcome("Blocked", "Run cancelled during dependency installation.")
                facts = (f"Detected {self.info.framework} ({self.info.kind})",
                         f"Install route: {' '.join(self.info.install)}", *self.info.observations)
                decision = decide_failure(output, [], set(), facts,
                                          phase="install", api_key=self.api_key)
                self.report(f"Recovery: {decision.reason}")
                if decision.action == "needs_input":
                    return Outcome("Needs input", decision.reason)
                if decision.action != "retry_install":
                    return Outcome("Blocked", decision.reason)
                code, output = self._command(install)
                if code:
                    return Outcome("Blocked", "Dependency installation failed again. " + output[-1200:])
            save_install(self.info.path)
        if self.cancelled.is_set():
            return Outcome("Blocked", "Run cancelled.")

        start = routes.index(previous) if previous else 0
        attempted = {start}
        result = self._launch_verify(routes[start])
        if result.state == "Running" or self.cancelled.is_set():
            if result.state == "Running":
                save_project(self.info.path, routes[start])
            return result
        failure_output = "\n".join(self.output).lower()
        if (self.info.framework == "django" and "unapplied migration" in failure_output
                and "no such table" in failure_output):
            recovered = self._recover_django_migrations(launch)
            if recovered is not None:
                if recovered.state == "Running":
                    save_project(self.info.path, launch)
                return recovered
        facts = (f"Detected {self.info.framework} ({self.info.kind})",
                 f"Attempted launch: {' '.join(self.info.launch)}", *self.info.observations)
        decision = decide_failure(result.detail, routes, attempted.copy(), facts,
                                  api_key=self.api_key)
        self.report(f"Recovery: {decision.reason}")
        if decision.action == "needs_input":
            return Outcome("Needs input", decision.reason)
        if decision.action != "retry_launch":
            return Outcome("Blocked", decision.reason)
        self.report("Trying another detected entry point after the failed launch.")
        result = self._launch_verify(routes[decision.candidate])
        if result.state == "Running":
            save_project(self.info.path, routes[decision.candidate])
        return result

    def _recover_django_migrations(self, launch: tuple[str, ...]) -> Outcome | None:
        """Migrate only a new SQLite file inside the selected project folder."""
        probe = (
            "import json; from django.conf import settings; "
            "db=settings.DATABASES['default']; "
            "print('FIRST_RUN_DB '+json.dumps([db['ENGINE'], str(db['NAME'])]))"
        )
        code, output = self._command((launch[0], "manage.py", "shell", "-c", probe), 30)
        match = re.search(r"^FIRST_RUN_DB (\[.*\])$", output, re.MULTILINE)
        if code or not match:
            return None
        try:
            engine, name = json.loads(match.group(1))
            database = Path(name).resolve()
            fresh = (engine == "django.db.backends.sqlite3" and name != ":memory:"
                     and database.is_relative_to(self.info.path)
                     and (not database.exists() or database.stat().st_size == 0))
        except (ValueError, OSError, TypeError):
            fresh = False
        if not fresh:
            return Outcome("Needs input", "Django reports unapplied migrations, but its database is not a fresh "
                           "project-local SQLite file. Review and apply the project's migrations yourself, "
                           "then click Continue setup.")
        self.report("Recovery: applying Django migrations to a fresh local SQLite database.")
        code, output = self._command((launch[0], "manage.py", "migrate", "--noinput"), 120)
        if code:
            return Outcome("Blocked", "Django migrations failed. " + output[-1200:])
        if self.cancelled.is_set():
            return Outcome("Blocked", "Run cancelled after migrations.")
        return self._launch_verify(launch)

    def _launch_routes(self, launch: tuple[str, ...]) -> list[tuple[str, ...]]:
        routes = [launch]
        if self.info.framework == "fastapi":
            for entry in ("main.py", "app.py"):
                if (self.info.path / entry).is_file():
                    route = (launch[0], "-m", "uvicorn", f"{entry[:-3]}:app", "--host", "127.0.0.1")
                    if route not in routes:
                        routes.append(route)
        elif self.info.framework == "flask":
            for entry in ("app.py", "main.py"):
                if (self.info.path / entry).is_file():
                    route = (launch[0], "-m", "flask", "--app", entry, "run", "--host", "127.0.0.1")
                    if route not in routes:
                        routes.append(route)
        elif self.info.kind == "node" and (self.info.path / "package.json").is_file():
            import json
            scripts = json.loads((self.info.path / "package.json").read_text()).get("scripts", {})
            for name in ("start", "dev", "serve"):
                route = ("npm", "run", name)
                if name in scripts and route not in routes:
                    routes.append(route)
        return routes

    def _launch_verify(self, launch: tuple[str, ...]) -> Outcome:
        self.output = []
        candidates = self._ports()
        ports = {urlparse(url).port for url in candidates}
        occupied = {
            port for port in ports
            if any(self._responds(f"http://{host}:{port}/") for host in ("127.0.0.1", "localhost"))
        }
        self.report("$ " + " ".join(launch))
        self.application = subprocess.Popen(
            launch, cwd=self.info.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", start_new_session=(os.name != "nt"), env=self._app_env(),
        )
        app = self.application

        def collect():
            assert app.stdout is not None
            for line in app.stdout:
                self.output.append(line.rstrip())
                if len(self.output) > 100:
                    self.output.pop(0)
                self.report(line.rstrip())

        self.app_reader = threading.Thread(target=collect, daemon=True)
        self.app_reader.start()
        deadline = time.monotonic() + STARTUP_TIMEOUT
        rejected: dict[str, int] = {}
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                self.stop()
                return Outcome("Blocked", "Run cancelled.")
            if app.poll() is not None:
                if self.app_reader:
                    self.app_reader.join(timeout=2)
                if app.stdout:
                    app.stdout.close()
                return Outcome("Blocked", "Application exited during startup. " + "\n".join(self.output[-20:])[-1600:])
            found = re.findall(r"https?://(?:localhost|127\.0\.0\.1):\d+", "\n".join(self.output))
            # A printed URL alone does not establish which process owns that port.
            # V1 verifies only the ports checked before launching the application.
            for url in dict.fromkeys([*found, *candidates]):
                port = urlparse(url).port
                if port not in ports or port in occupied:
                    continue
                try:
                    with urlopen(url, timeout=0.7) as response:
                        status = response.status
                    if 200 <= status < 400 and app.poll() is None:
                        return Outcome("Running", f"HTTP {status} from {url}", url)
                    rejected[url] = status
                except HTTPError as exc:
                    rejected[url] = exc.code
                except (OSError, URLError):
                    pass
            time.sleep(0.5)
        self._stop(app)
        if self.app_reader:
            self.app_reader.join(timeout=2)
        if app.stdout:
            app.stdout.close()
        if rejected:
            responses = ", ".join(f"HTTP {status} from {url}" for url, status in rejected.items())
            return Outcome("Blocked", "Application responded, but no checked route verified usable: " + responses
                           + ". See Output for startup details.")
        return Outcome("Blocked", f"Application did not respond over HTTP within {STARTUP_TIMEOUT} seconds. "
                       + "\n".join(self.output[-15:])[-1200:])

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
                 "streamlit": (8501,), "Node web": (3000, 5173, 8080, 4173)}
        return [f"http://127.0.0.1:{port}/" for port in ports.get(self.info.framework, ())]
