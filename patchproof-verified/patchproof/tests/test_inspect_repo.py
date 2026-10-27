"""Tests for the PatchProof repository inspector (scripts/inspect_repo.py)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

import inspect_repo as ir  # noqa: E402


def run_cli(args, cwd=None):
    """Run the inspector as a subprocess; return (exit_code, parsed_stdout)."""
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "inspect_repo.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return completed.returncode, json.loads(completed.stdout)


def make_git_repo(path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    git("init", "-q")
    git("config", "user.name", "PatchProof Tests")
    git("config", "user.email", "tests@patchproof.invalid")
    (path / "tracked.txt").write_text("hello\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-q", "-m", "initial")


class TestTargetValidation(unittest.TestCase):
    def test_nonexistent_path_exits_2(self):
        code, output = run_cli(["definitely_missing_12345"])
        self.assertEqual(code, 2)
        self.assertFalse(output["valid"])
        self.assertIn("does not exist", output["error"])

    def test_file_target_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "file.txt"
            target.write_text("x", encoding="utf-8")
            code, output = run_cli([str(target)])
        self.assertEqual(code, 2)
        self.assertIn("not a directory", output["error"])

    def test_null_byte_path_rejected(self):
        with self.assertRaises(ir.TargetError):
            ir._resolve_target("C:\\nul\x00byte")

    def test_max_files_below_one_exits_2(self):
        code, output = run_cli([".", "--max-files", "0"])
        self.assertEqual(code, 2)
        self.assertIn("--max-files", output["error"])


class TestDetection(unittest.TestCase):
    def test_python_configs_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[tool.pytest.ini_options]\n", encoding="utf-8"
            )
            (root / "requirements.txt").write_text("requests\n", encoding="utf-8")
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        names = [entry["name"] for entry in output["languages"]]
        self.assertIn("python", names)
        evidence = [
            entry["evidence"]
            for entry in output["languages"]
            if entry["name"] == "python"
        ][0]
        self.assertIn("pyproject.toml", evidence)
        self.assertIn("requirements.txt", evidence)
        purposes = [cmd["purpose"] for cmd in output["suggested_commands"]]
        self.assertIn("test", purposes)

    def test_node_frameworks_and_tooling_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {"react": "^18.0.0"},
                        "devDependencies": {
                            "jest": "^29.0.0",
                            "eslint": "^8.0.0",
                            "typescript": "^5.0.0",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        names = [entry["name"] for entry in output["languages"]]
        self.assertIn("javascript", names)
        self.assertIn("typescript", names)
        framework_names = [f["name"] for f in output["frameworks"]]
        self.assertIn("react", framework_names)
        commands = [c["command"] for c in output["suggested_commands"]]
        self.assertIn("npm test", commands)
        self.assertIn("npx tsc --noEmit", commands)

    def test_malformed_package_json_warns_and_still_detects_javascript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{not json", encoding="utf-8")
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        names = [entry["name"] for entry in output["languages"]]
        self.assertIn("javascript", names)
        self.assertTrue(
            any("not valid JSON" in w for w in output["warnings"])
        )

    def test_dockerfile_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Dockerfile").write_text("FROM python:3.13\n", encoding="utf-8")
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        names = [entry["name"] for entry in output["languages"]]
        self.assertIn("container", names)

    def test_test_files_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("", encoding="utf-8")
            (root / "test_calc.py").write_text("", encoding="utf-8")
            (root / "test_parser.py").write_text("", encoding="utf-8")
            (root / "module.py").write_text("", encoding="utf-8")
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        self.assertEqual(output["test_files_found"], 2)

    def test_empty_tree_warns_about_missing_language_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_cli([str(tmp)])
        self.assertEqual(code, 0)
        self.assertEqual(output["languages"], [])
        self.assertTrue(
            any("no language configuration" in w for w in output["warnings"])
        )


class TestGitState(unittest.TestCase):
    def test_dirty_working_tree_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_git_repo(root)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            (root / "untracked.txt").write_text("new\n", encoding="utf-8")
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        self.assertTrue(output["git"]["available"])
        self.assertTrue(output["git"]["is_repository"])
        self.assertTrue(output["git"]["dirty"])
        self.assertGreaterEqual(output["git"]["tracked_modified"], 1)
        self.assertGreaterEqual(output["git"]["untracked"], 1)
        self.assertIsNotNone(output["git"]["revision"])

    def test_clean_working_tree_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_git_repo(root)
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        self.assertTrue(output["git"]["is_repository"])
        self.assertFalse(output["git"]["dirty"])
        self.assertEqual(output["git"]["tracked_modified"], 0)
        self.assertEqual(output["git"]["untracked"], 0)

    def test_non_git_directory_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_cli([str(tmp)])
        self.assertEqual(code, 0)
        self.assertTrue(output["git"]["available"])
        self.assertFalse(output["git"]["is_repository"])

    def test_git_missing_degrades_to_warning(self):
        original_run = ir._run

        def fake_run(command, cwd):
            raise FileNotFoundError("git")

        ir._run = fake_run
        try:
            with tempfile.TemporaryDirectory() as tmp:
                warnings: list[str] = []
                state = ir._git_state(tmp, warnings)
        finally:
            ir._run = original_run
        self.assertFalse(state["available"])
        self.assertTrue(
            any("git executable not found" in w for w in warnings)
        )

    def test_git_timeout_degrades_to_warning(self):
        original_run = ir._run

        def fake_run(command, cwd):
            return -1, "", "timed out after 15s"

        ir._run = fake_run
        try:
            with tempfile.TemporaryDirectory() as tmp:
                warnings: list[str] = []
                state = ir._git_state(tmp, warnings)
        finally:
            ir._run = original_run
        self.assertTrue(state["available"])
        self.assertFalse(state["is_repository"])
        self.assertTrue(any("timed out" in w for w in warnings))


class TestScanBounds(unittest.TestCase):
    def test_node_modules_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("", encoding="utf-8")
            node_modules = root / "node_modules"
            node_modules.mkdir()
            for index in range(20):
                (node_modules / f"dep{index}.js").write_text("", encoding="utf-8")
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        self.assertIn("node_modules", output["skipped_directories"])
        self.assertEqual(output["files_scanned"], 1)

    def test_max_files_truncates_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(10):
                (root / f"data_{index}.txt").write_text("", encoding="utf-8")
            code, output = run_cli([str(root), "--max-files", "3"])
        self.assertEqual(code, 0)
        self.assertEqual(output["files_scanned"], 3)
        self.assertTrue(output["scan_truncated"])
        self.assertTrue(any("truncated" in w for w in output["warnings"]))


class TestSuggestionsAreLabeled(unittest.TestCase):
    def test_commands_marked_as_suggestions_not_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[tool.pytest.ini_options]\n", encoding="utf-8"
            )
            code, output = run_cli([str(root)])
        self.assertEqual(code, 0)
        self.assertTrue(output["suggested_commands"])
        for command in output["suggested_commands"]:
            self.assertIn("basis", command)
            self.assertIn("purpose", command)
            self.assertIn("command", command)


if __name__ == "__main__":
    unittest.main()
