import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from io import BytesIO

from first_run.agent import decide_failure, failure_summary
from first_run.history import recent, saved_launch
from first_run.inspect import inspect_project
from first_run.runner import SetupRunner


class RunnerTests(unittest.TestCase):
    def test_existing_local_server_is_not_claimed_as_new_app(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"unrelated")

            def log_message(self, *_):
                pass

        server = None
        for port in (3000, 8080, 4173):
            try:
                server = HTTPServer(("127.0.0.1", port), Handler)
                break
            except OSError:
                continue
        if server is None:
            self.skipTest("All test ports are occupied")
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with TemporaryDirectory() as directory:
                path = Path(directory)
                (path / "package.json").write_text(json.dumps({
                    "name": "occupied-port-test", "version": "1.0.0",
                    "scripts": {"start": "node server.js"},
                }))
                (path / "server.js").write_text(
                    f"console.log('http://localhost:{port}'); setInterval(()=>{{}}, 1000)"
                )
                started = threading.Event()
                runner = SetupRunner(
                    inspect_project(path),
                    lambda line: started.set() if line == "$ npm run start" else None,
                    threading.Event(),
                )
                result = []
                worker = threading.Thread(target=lambda: result.append(runner.run()))
                worker.start()
                self.assertTrue(started.wait(10))
                time.sleep(1)
                self.assertFalse(result, "First Run claimed the unrelated server")
                runner.stop()
                worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result[0].state, "Blocked")
        finally:
            server.shutdown()
            server.server_close()

    def test_missing_env_value_needs_input_before_install(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
            (path / ".env.example").write_text("SERVICE_API_KEY=\n")
            outcome = SetupRunner(inspect_project(path), lambda _: None, threading.Event()).run()
            self.assertEqual(outcome.state, "Needs input")
            self.assertIn("SERVICE_API_KEY", outcome.detail)
            self.assertIn(str(path / ".env"), outcome.detail)
            self.assertFalse((path / "node_modules").exists())

    def test_cancelled_before_setup_does_not_create_environment(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "requirements.txt").write_text("fastapi\nuvicorn\n")
            (path / "main.py").write_text("app = None\n")
            (path / ".env.example").write_text("SERVICE_KEY=\n")
            cancelled = threading.Event()
            cancelled.set()
            outcome = SetupRunner(inspect_project(path), lambda _: None, cancelled).run()
            self.assertIn("cancelled", outcome.detail)
            self.assertFalse((path / ".env").exists())
            self.assertFalse((path / ".venv").exists())

    @unittest.skipIf(os.name == "nt", "Uses a POSIX test executable")
    def test_cancel_during_install_stops_before_launch(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
            npm = path / "npm"
            npm.write_text("#!/bin/sh\nif [ \"$1\" = '--version' ]; then echo 1; exit 0; fi\nexec sleep 60\n")
            npm.chmod(0o755)
            with patch.dict(os.environ, {"PATH": str(path) + os.pathsep + os.environ["PATH"]}):
                started = threading.Event()
                cancelled = threading.Event()
                runner = SetupRunner(inspect_project(path), lambda line: started.set() if line == "$ npm install" else None, cancelled)
                result = []
                thread = threading.Thread(target=lambda: result.append(runner.run()))
                thread.start()
                self.assertTrue(started.wait(3))
                runner.stop()
                thread.join(4)
                self.assertFalse(thread.is_alive())
                self.assertIsNone(runner.application)
                self.assertEqual(result[0].state, "Blocked")

    def test_recovery_rejects_repeated_route_without_model_call(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            decision = decide_failure("Failed", [("npm", "run", "start")], {0}, ())
        self.assertEqual(decision.action, "blocked")

    def test_failure_summary_skips_traceback_closing_lines(self):
        node = "Application exited.\nFailed to connect to MongoDB: Error: querySrv ECONNREFUSED\n    at QueryReqWrap.onresolve\n  code: 'ECONNREFUSED'\n}"
        python = "Traceback (most recent call last):\n  File /tmp/main.py, line 12\nNameError: name 'SingletonMeta' is not defined"
        self.assertIn("MongoDB", failure_summary(node))
        self.assertIn("NameError", failure_summary(python))

    def test_model_cannot_select_unlisted_command(self):
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
            "action": "retry_launch", "reason": "try it", "candidate": 99,
        })}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            with patch("first_run.agent.urlopen") as request:
                request.return_value.__enter__.return_value = BytesIO(json.dumps(response).encode())
                decision = decide_failure("Failed", [("npm", "run", "dev"), ("npm", "run", "start")], {0}, ())
        self.assertEqual(decision.action, "retry_launch")
        self.assertEqual(decision.candidate, 1)

    def test_model_can_choose_input_or_blocker_without_starting_another_route(self):
        routes = [("npm", "run", "dev"), ("npm", "run", "start")]
        for action in ("needs_input", "blocked"):
            with self.subTest(action=action):
                reason = "SERVICE_API_KEY is required" if action == "needs_input" else "MongoDB service is unavailable"
                response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                    "action": action, "reason": reason, "candidate": -1,
                })}]}]}
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                    with patch("first_run.agent.urlopen") as request:
                        request.return_value.__enter__.return_value = BytesIO(json.dumps(response).encode())
                        decision = decide_failure("MongoDB connection failed", routes, {0}, ())
                self.assertEqual(decision.action, action)
                self.assertEqual(decision.candidate, -1)

    def test_malformed_model_response_falls_back_to_known_route(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            with patch("first_run.agent.urlopen") as request:
                request.return_value.__enter__.return_value = BytesIO(b'{"output": null}')
                decision = decide_failure("Launch failed", [("npm", "run", "dev"), ("npm", "run", "start")], {0}, ())
        self.assertEqual(decision.action, "retry_launch")
        self.assertEqual(decision.candidate, 1)
        self.assertIn("TypeError", decision.reason)

    def test_provider_key_is_not_passed_to_project_commands(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
            runner = SetupRunner(inspect_project(path), lambda _: None, threading.Event())
            with patch.dict(os.environ, {"OPENAI_API_KEY": "private-test-value"}):
                code, output = runner._command((sys.executable, "-c", "import os; print(os.getenv('OPENAI_API_KEY', 'absent'))"))
                self.assertEqual(code, 0)
                self.assertEqual(output.strip(), "absent")
                self.assertNotIn("OPENAI_API_KEY", runner._app_env())

    def test_provider_key_does_not_satisfy_project_env_requirement(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
            (path / ".env.example").write_text("OPENAI_API_KEY=\n")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "private-test-value"}):
                result = SetupRunner(inspect_project(path), lambda _: None, threading.Event()).run()
            self.assertEqual(result.state, "Needs input")
            self.assertIn("OPENAI_API_KEY", result.detail)

    def test_saved_node_route_skips_unchanged_install_but_not_changed_manifest(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project"
            path.mkdir()
            (path / "package.json").write_text(json.dumps({"name": "rerun-test", "version": "1.0.0", "scripts": {"start": "node server.js"}}))
            (path / "server.js").write_text("require('http').createServer((q,r)=>r.end('ready')).listen(3000,'127.0.0.1')")
            with patch("first_run.history.history_path", return_value=Path(directory) / "history.json"):
                logs = []
                first = SetupRunner(inspect_project(path), logs.append, threading.Event())
                try:
                    self.assertEqual(first.run().state, "Running")
                finally:
                    first.stop()
                self.assertEqual(saved_launch(path), ("npm", "run", "start"))
                second = SetupRunner(inspect_project(path), logs.append, threading.Event())
                try:
                    self.assertEqual(second.run(reuse=True).state, "Running")
                finally:
                    second.stop()
                self.assertTrue(any("installation skipped" in line for line in logs))
                (path / "package.json").write_text(json.dumps({
                    "name": "rerun-test", "version": "1.0.0",
                    "scripts": {"start": "node server.js", "test": "node --version"},
                }))
                self.assertIsNone(saved_launch(path))
                logs.clear()
                third = SetupRunner(inspect_project(path), logs.append, threading.Event())
                try:
                    self.assertEqual(third.run(reuse=True).state, "Running")
                finally:
                    third.stop()
                self.assertTrue(any(line in ("$ npm install", "$ npm ci") for line in logs))
                self.assertFalse(any("installation skipped" in line for line in logs))

    def test_failed_dev_script_retries_detected_start_without_provider_key(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project"
            path.mkdir()
            (path / "package.json").write_text(json.dumps({
                "name": "route-test", "version": "1.0.0",
                "scripts": {"dev": "node broken.js", "start": "node server.js"},
            }))
            (path / "broken.js").write_text("process.exit(1)")
            (path / "server.js").write_text("require('http').createServer((q,r)=>r.end('ready')).listen(3000,'127.0.0.1')")
            with patch("first_run.history.history_path", return_value=Path(directory) / "history.json"):
                with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                    logs = []
                    runner = SetupRunner(inspect_project(path), logs.append, threading.Event())
                    try:
                        result = runner.run()
                        self.assertEqual(result.state, "Running")
                        self.assertEqual(saved_launch(path), ("npm", "run", "start"))
                        self.assertTrue(any("Trying another detected entry point" in line for line in logs))
                    finally:
                        runner.stop()

    def test_model_selects_known_start_route_after_real_launch_failure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project"
            path.mkdir()
            (path / "package.json").write_text(json.dumps({
                "name": "model-route-test", "version": "1.0.0",
                "scripts": {"dev": "node broken.js", "start": "node server.js"},
            }))
            (path / "broken.js").write_text("console.error('dev failed'); process.exit(1)")
            (path / "server.js").write_text("require('http').createServer((q,r)=>r.end('ready')).listen(3000,'127.0.0.1')")
            response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "action": "retry_launch", "reason": "Use the detected start script", "candidate": 1,
            })}]}]}
            with patch("first_run.history.history_path", return_value=Path(directory) / "history.json"):
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                    with patch("first_run.agent.urlopen") as request:
                        request.return_value.__enter__.return_value = BytesIO(json.dumps(response).encode())
                        runner = SetupRunner(inspect_project(path), lambda _: None, threading.Event())
                        try:
                            self.assertEqual(runner.run().state, "Running")
                            self.assertEqual(saved_launch(path), ("npm", "run", "start"))
                            sent = json.loads(request.call_args.args[0].data)
                            self.assertEqual(json.loads(sent["input"])["available_launch_candidates"][0]["index"], 1)
                        finally:
                            runner.stop()

    def test_source_bug_is_blocked_without_source_changes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "package.json").write_text(json.dumps({
                "name": "source-bug-test", "version": "1.0.0", "scripts": {"start": "node broken.js"},
            }))
            source = "throw new Error('source bug needs a code fix')\n"
            (path / "broken.js").write_text(source)
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                outcome = SetupRunner(inspect_project(path), lambda _: None, threading.Event()).run()
            self.assertEqual(outcome.state, "Blocked")
            self.assertIn("source bug needs a code fix", outcome.detail)
            self.assertEqual((path / "broken.js").read_text(), source)


if __name__ == "__main__":
    unittest.main()
