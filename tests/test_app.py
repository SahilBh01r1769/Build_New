import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
