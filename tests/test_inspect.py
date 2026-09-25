import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from first_run.inspect import inspect_project
from first_run.source import prepare_source


class InspectTests(unittest.TestCase):
    def test_fastapi_requirements_and_entry(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "requirements.txt").write_text("fastapi\nuvicorn\n")
            (path / "main.py").write_text("app = None\n")
            info = inspect_project(path)
            self.assertEqual(info.framework, "fastapi")
            self.assertEqual(info.launch[:2], ("uvicorn", "main:app"))

    def test_node_prefers_lockfile_and_dev_script(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite", "start": "node server.js"}}))
            (path / "package-lock.json").write_text("{}")
            info = inspect_project(path)
            self.assertEqual(info.install, ("npm", "ci"))
            self.assertEqual(info.launch, ("npm", "run", "dev"))

    def test_local_source_must_exist(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(prepare_source(directory), Path(directory).resolve())
            with self.assertRaises(ValueError):
                prepare_source(str(Path(directory) / "missing"))


if __name__ == "__main__":
    unittest.main()
