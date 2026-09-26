import json
import os
from pathlib import Path
import shutil
import socket
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from first_run.app import MainWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_running_status_clears_when_process_exits(self):
        window = MainWindow()
        window.address = "http://127.0.0.1:3000/"
        window.state.setText("Running")
        window.open_button.setEnabled(True)
        process = Mock()
        process.poll.return_value = 1
        runner = SimpleNamespace(application=process, stop=Mock())
        window.process_runner = runner

        window.check_process()

        self.assertEqual(window.state.text(), "Blocked")
        self.assertIsNone(window.address)
        self.assertFalse(window.open_button.isEnabled())
        runner.stop.assert_called_once()
        window.process_watch.stop()
        window.close()

    @unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "Node and npm required")
    def test_output_after_setup_worker_exits_reaches_window(self):
        port = None
        for candidate in (3000, 5173, 8080, 4173):
            try:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", candidate))
                port = candidate
                break
            except OSError:
                continue
        if port is None:
            self.skipTest("All supported Node ports are occupied")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project"
            path.mkdir()
            (path / "package.json").write_text(json.dumps({
                "name": "late-output-test", "version": "1.0.0",
                "scripts": {"start": "node server.js"},
            }))
            (path / "server.js").write_text(
                "const fs = require('fs'); const http = require('http');\n"
                f"http.createServer((req, res) => res.end('ok')).listen({port}, '127.0.0.1');\n"
                "const timer = setInterval(() => { if (fs.existsSync('release-output')) {\n"
                "  console.log('late application output'); clearInterval(timer);\n"
                "}}, 50);\n"
            )
            with patch("first_run.history.history_path", return_value=Path(directory) / "history.json"):
                window = MainWindow()
                try:
                    window.source.setText(str(path))
                    window.start.click()

                    def wait_for(predicate, timeout=20):
                        deadline = time.monotonic() + timeout
                        while time.monotonic() < deadline:
                            self.app.processEvents()
                            if predicate():
                                return True
                            time.sleep(.05)
                        return False

                    self.assertTrue(wait_for(lambda: window.state.text() == "Running" and window.thread is None),
                                    window.current.text())
                    (path / "release-output").touch()
                    self.assertTrue(wait_for(lambda: "late application output" in window.output.toPlainText()),
                                    window.output.toPlainText())
                finally:
                    window.stop_run()
                    window.process_watch.stop()
                    window.close()


if __name__ == "__main__":
    unittest.main()
