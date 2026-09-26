import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from first_run.inspect import inspect_project
from first_run.source import prepare_source


class InspectTests(unittest.TestCase):
    def test_bundled_example_has_a_supported_launch_route(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "flask_hello"
        info = inspect_project(example)
        self.assertEqual(info.framework, "flask")
        self.assertEqual(info.launch, ("flask", "--app", "app.py", "run", "--host", "127.0.0.1"))

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

    def test_single_nested_component_and_fastapi_module(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend"
            (backend / "src" / "api").mkdir(parents=True)
            (backend / "requirements.txt").write_text("fastapi\nuvicorn\n")
            (backend / "src" / "api" / "main.py").write_text("app = None\n")
            info = inspect_project(root)
            self.assertEqual(info.path, backend)
            self.assertEqual(info.launch[:2], ("uvicorn", "src.api.main:app"))

    def test_multiple_components_request_selection_and_ignore_dependencies(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("frontend", "backend", "node_modules/hidden"):
                component = root / name
                component.mkdir(parents=True)
                (component / "package.json").write_text('{"scripts":{"dev":"vite"}}')
            info = inspect_project(root)
            self.assertEqual(info.framework, "Multiple components")
            self.assertIn("frontend", info.observations[0])
            self.assertIn("backend", info.observations[0])
            self.assertNotIn("hidden", info.observations[0])

    def test_node_minimum_version_is_reported_before_setup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({
                "engines": {"node": ">=20"}, "scripts": {"start": "node server.js"},
            }))
            with patch("first_run.inspect._version", side_effect=["node: v18.2.0", "npm: 9.0.0"]):
                info = inspect_project(root)
            self.assertIn("Node 20.0", info.runtime_issue)
            self.assertIn("Node 18.2", info.runtime_issue)

    def test_python_requirement_above_current_version_needs_input(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "future-web"\nversion = "0.1"\n'
                'requires-python = ">=99.0"\ndependencies = ["fastapi", "uvicorn"]\n'
            )
            (root / "main.py").write_text("app = None\n")
            info = inspect_project(root)
            self.assertIn("Python 99.0", info.runtime_issue)

    def test_local_source_must_exist(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(prepare_source(directory), Path(directory).resolve())
            with self.assertRaises(ValueError):
                prepare_source(str(Path(directory) / "missing"))


if __name__ == "__main__":
    unittest.main()
