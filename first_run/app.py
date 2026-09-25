"""Small task-oriented desktop shell for a First Run session."""

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from first_run.source import prepare_source
from first_run.inspect import ProjectInfo, inspect_project


class SourceWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, source: str, destination: str):
        super().__init__()
        self.source = source
        self.destination = destination

    def run(self):
        try:
            self.finished.emit(inspect_project(prepare_source(self.source, self.destination)))
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("First Run")
        self.resize(760, 560)
        self.thread = None
        self.worker = None

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

        self.start = QPushButton("Inspect project")
        self.start.clicked.connect(self.open_project)
        self.state = QLabel("Ready")
        self.current = QLabel("Choose a local folder or repository URL.")
        self.plan = QLabel("No plan yet")
        self.plan.setWordWrap(True)
        self.output = QTextEdit()
        self.output.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.start)
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
        self.state.setText("Opening")
        self.current.setText("Resolving project source…")
        self.thread = QThread(self)
        self.worker = SourceWorker(self.source.text(), self.destination.text())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.source_ready)
        self.worker.failed.connect(self.source_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: self.start.setEnabled(True))
        self.thread.start()

    def source_ready(self, info: ProjectInfo):
        self.state.setText("Inspected" if info.launch else "Blocked")
        self.current.setText(f"{info.framework} · {info.path}")
        if info.launch:
            steps = ["Create virtual environment"] if info.kind == "python" else []
            steps.extend(["Install dependencies", "Launch application", "Verify HTTP response"])
            self.plan.setText(" → ".join(steps))
            self.output.append(f"Install: {' '.join(info.install)}\nLaunch: {' '.join(info.launch)}")
        else:
            self.plan.setText("No safe setup route determined.")
        self.output.append("\n".join(info.observations))

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
