"""Small task-oriented desktop shell for a First Run session."""

import sys
import threading
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from first_run.source import prepare_source
from first_run.inspect import ProjectInfo, inspect_project
from first_run.runner import Outcome, SetupRunner


class SourceWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    inspected = Signal(object)
    output = Signal(str)

    def __init__(self, source: str, destination: str):
        super().__init__()
        self.source = source
        self.destination = destination
        self.cancelled = threading.Event()
        self.runner = None

    def run(self):
        try:
            info = inspect_project(prepare_source(self.source, self.destination))
            self.inspected.emit(info)
            self.runner = SetupRunner(info, self.output.emit, self.cancelled)
            self.finished.emit(self.runner.run())
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("First Run")
        self.resize(760, 560)
        self.thread = None
        self.worker = None
        self.process_runner = None
        self.address = None

        self.source = QLineEdit()
        self.source.setPlaceholderText("Local project folder or public HTTPS Git URL")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_source)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source)
        source_row.addWidget(browse)

        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Folder to create when cloning")
        destination_button = QPushButton("Choose…")
        destination_button.clicked.connect(self.choose_destination)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination)
        destination_row.addWidget(destination_button)

        form = QFormLayout()
        form.addRow("Project", source_row)
        form.addRow("Clone to", destination_row)

        self.start = QPushButton("Set up and run")
        self.start.clicked.connect(self.open_project)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_run)
        self.open_button = QPushButton("Open app")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(lambda: webbrowser.open(self.address) if self.address else None)
        actions = QHBoxLayout()
        actions.addWidget(self.start)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.open_button)
        self.state = QLabel("Ready")
        self.current = QLabel("Choose a local folder or repository URL.")
        self.plan = QLabel("No plan yet")
        self.plan.setWordWrap(True)
        self.output = QTextEdit()
        self.output.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(QLabel("Current run"))
        layout.addWidget(self.state)
        layout.addWidget(self.current)
        layout.addWidget(QLabel("Setup plan"))
        layout.addWidget(self.plan)
        layout.addWidget(QLabel("Output"))
        layout.addWidget(self.output, 1)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)

    def browse_source(self):
        path = QFileDialog.getExistingDirectory(self, "Select project folder")
        if path:
            self.source.setText(path)

    def choose_destination(self):
        parent = QFileDialog.getExistingDirectory(self, "Select parent folder")
        if parent:
            name = Path(self.source.text().rstrip("/")).name.removesuffix(".git") or "project"
            self.destination.setText(str(Path(parent) / name))

    def open_project(self):
        self.start.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.address = None
        self.state.setText("Opening")
        self.current.setText("Resolving project source…")
        self.thread = QThread(self)
        self.worker = SourceWorker(self.source.text(), self.destination.text())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.inspected.connect(self.source_ready)
        self.worker.output.connect(self.output.append)
        self.worker.finished.connect(self.run_finished)
        self.worker.failed.connect(self.source_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.thread_finished)
        self.thread.start()

    def thread_finished(self):
        self.start.setEnabled(True)
        self.stop_button.setEnabled(self.address is not None)

    def stop_run(self):
        if self.thread and self.thread.isRunning() and self.worker:
            self.worker.cancelled.set()
            if self.worker.runner:
                self.worker.runner.stop()
        elif self.process_runner:
            self.process_runner.stop()
        self.stop_button.setEnabled(False)

    def closeEvent(self, event):
        self.stop_run()
        if self.thread and self.thread.isRunning():
            self.thread.wait(4000)
        super().closeEvent(event)

    def source_ready(self, info: ProjectInfo):
        self.state.setText("Setting up" if info.launch else "Blocked")
        self.current.setText(f"{info.framework} · {info.path}")
        if info.launch:
            steps = ["Create virtual environment"] if info.kind == "python" else []
            steps.extend(["Install dependencies", "Launch application", "Verify HTTP response"])
            self.plan.setText(" → ".join(steps))
            self.output.append(f"Install: {' '.join(info.install)}\nLaunch: {' '.join(info.launch)}")
        else:
            self.plan.setText("No safe setup route determined.")
        self.output.append("\n".join(info.observations))

    def run_finished(self, outcome: Outcome):
        self.process_runner = self.worker.runner
        self.state.setText(outcome.state)
        self.current.setText(outcome.detail)
        self.current.setWordWrap(True)
        self.address = outcome.address
        self.open_button.setEnabled(bool(outcome.address))
        self.stop_button.setEnabled(bool(outcome.address))

    def source_failed(self, message: str):
        self.state.setText("Blocked")
        self.current.setText(message)
        self.output.append(message)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
