#!/usr/bin/env python3
"""Read-only repository inventory for PatchProof (PHASE 1 — UNDERSTAND).

Usage:
    python inspect_repo.py [PATH] [--max-files N]

Prints a JSON inventory on stdout: operating system and runtime facts, git
state, detected languages and frameworks (from configuration files), test file
counts, and suggested verification commands.

Safety properties:
  - Never writes or modifies anything in the scanned tree.
  - Never requires network access.
  - Bounded scan (default 2000 files) and per-command timeouts.
  - Distinguishes observed facts ("basis": "observed") from suggestions.

Exit codes: 0 success, 2 usage/target error.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TOOL = "patchproof-inspect-repo"
SCHEMA_VERSION = "1.0"

DEFAULT_MAX_FILES = 2000
COMMAND_TIMEOUT_S = 15
CONFIG_READ_LIMIT = 64 * 1024

SKIPPED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".bzr",
    "node_modules", "bower_components", "vendor",
    "venv", ".venv", "env", ".tox", ".nox",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode",
    "dist", "build", "target", "out",
    ".next", ".nuxt", ".output", ".turbo",
    "coverage", ".coverage",
}

TEST_FILE_PATTERNS = (
    "test_*.py", "*_test.py",
    "*.test.js", "*.test.ts", "*.test.jsx", "*.test.tsx",
    "*.spec.js", "*.spec.ts", "*.spec.jsx", "*.spec.tsx",
)

# Top-level configuration file -> detected language(s)
CONFIG_LANGUAGES = {
    "pyproject.toml": ["python"],
    "requirements.txt": ["python"],
    "setup.py": ["python"],
    "setup.cfg": ["python"],
    "Pipfile": ["python"],
    "Pipfile.lock": ["python"],
    "package.json": ["javascript"],
    "tsconfig.json": ["typescript"],
    "Cargo.toml": ["rust"],
    "go.mod": ["go"],
    "pom.xml": ["java"],
    "build.gradle": ["java"],
    "build.gradle.kts": ["java"],
    "composer.json": ["php"],
    "Gemfile": ["ruby"],
    "Dockerfile": ["container"],
    "docker-compose.yml": ["container"],
    "docker-compose.yaml": ["container"],
}

NODE_FRAMEWORKS = {
    "react": "react",
    "react-dom": "react",
    "next": "next.js",
    "vue": "vue",
    "nuxt": "nuxt",
    "angular": "angular",
    "@angular/core": "angular",
    "express": "express",
    "fastify": "fastify",
    "koa": "koa",
    "svelte": "svelte",
    "electron": "electron",
}

NODE_TOOLING = {
    "jest": ("test", "npm test"),
    "vitest": ("test", "npx vitest run"),
    "mocha": ("test", "npx mocha"),
    "playwright": ("test", "npx playwright test"),
    "eslint": ("lint", "npx eslint ."),
    "typescript": ("typecheck", "npx tsc --noEmit"),
}

PYPROJECT_MARKERS = {
    "pytest": ("test", "python -m pytest -q"),
    "ruff": ("lint", "python -m ruff check ."),
    "mypy": ("typecheck", "python -m mypy ."),
}


class TargetError(Exception):
    """Raised when the scan target is missing, invalid, or unsafe."""


def _resolve_target(path: str) -> str:
    """Validate the target path and return its normalized absolute form."""
    if "\x00" in path:
        raise TargetError("target path contains a null byte")
    normalized = os.path.realpath(os.path.abspath(os.fspath(path)))
    if not os.path.exists(normalized):
        raise TargetError(f"target path does not exist: {path!r}")
    if not os.path.isdir(normalized):
        raise TargetError(f"target path is not a directory: {path!r}")
    return normalized


def _run(command: Sequence[str], cwd: str) -> tuple[int, str, str]:
    """Run a read-only command with a timeout. Never raises except for bugs."""
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_S,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError:
        raise
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {COMMAND_TIMEOUT_S}s"
    except OSError as exc:
        return -1, "", str(exc)


def _git_state(root: str, warnings: list[str]) -> dict[str, Any]:
    """Collect git facts for *root*. Never raises; degrades to warnings."""
    state: dict[str, Any] = {"available": False, "is_repository": False}
    try:
        returncode, _out, _err = _run(
            ["git", "rev-parse", "--is-inside-work-tree"], root
        )
    except FileNotFoundError:
        state["available"] = False
        warnings.append(
            "git executable not found on PATH; repository state is unknown"
        )
        return state

    state["available"] = True
    if returncode != 0:
        if returncode == -1:
            warnings.append("git rev-parse timed out; repository state unknown")
        return state
    state["is_repository"] = True

    returncode, stdout, _err = _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], root
    )
    if returncode == 0:
        state["branch"] = stdout.strip()

    returncode, stdout, _err = _run(["git", "rev-parse", "HEAD"], root)
    if returncode == 0:
        state["revision"] = stdout.strip()

    returncode, stdout, _err = _run(["git", "status", "--porcelain"], root)
    if returncode == 0:
        lines = stdout.splitlines()
        tracked_modified = staged = untracked = 0
        for line in lines:
            if len(line) < 2:
                continue
            index_flag, worktree_flag = line[0], line[1]
            if index_flag in "MADR":
                staged += 1
            if worktree_flag in "MD":
                tracked_modified += 1
            if index_flag == "?":
                untracked += 1
        state["tracked_modified"] = tracked_modified
        state["staged"] = staged
        state["untracked"] = untracked
        state["status_lines"] = lines[:50]
        state["status_truncated"] = len(lines) > 50
        state["dirty"] = bool(lines)
    else:
        warnings.append(
            f"git status failed (exit {returncode}); working tree state unknown"
        )
    return state


def _read_config_snippet(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(CONFIG_READ_LIMIT)
    except OSError:
        return None


def _detect_node_frameworks(
    package_json_path: Path, warnings: list[str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (frameworks, tooling) inferred from package.json."""
    frameworks: list[dict[str, str]] = []
    tooling: list[dict[str, str]] = []
    snippet = _read_config_snippet(package_json_path)
    if snippet is None:
        warnings.append(f"could not read {package_json_path.name}")
        return frameworks, tooling
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError as exc:
        warnings.append(
            f"{package_json_path.name} is not valid JSON (line {exc.lineno}); "
            "dependency analysis skipped"
        )
        return frameworks, tooling
    if not isinstance(data, dict):
        return frameworks, tooling
    deps: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        content = data.get(section)
        if isinstance(content, dict):
            for key, value in content.items():
                if isinstance(key, str) and isinstance(value, str):
                    deps[key] = value
    for package, name in NODE_FRAMEWORKS.items():
        if package in deps:
            frameworks.append(
                {"name": name, "evidence": f"package.json dependency {package}"}
            )
    for package, (purpose, command) in NODE_TOOLING.items():
        if package in deps:
            tooling.append(
                {
                    "purpose": purpose,
                    "command": command,
                    "basis": f"package.json devDependency {package}",
                }
            )
    if deps.get("scripts") or data.get("scripts"):
        scripts = data.get("scripts")
        if isinstance(scripts, dict):
            for name, script in scripts.items():
                if name in ("test", "lint", "build", "typecheck") and isinstance(
                    script, str
                ):
                    tooling.append(
                        {
                            "purpose": name,
                            "command": f"npm run {name}",
                            "basis": f"package.json script {name!r}",
                        }
                    )
    return frameworks, tooling


def _detect_python_tooling(
    pyproject_path: Path, warnings: list[str]
) -> list[dict[str, str]]:
    tooling: list[dict[str, str]] = []
    snippet = _read_config_snippet(pyproject_path)
    if snippet is None:
        warnings.append(f"could not read {pyproject_path.name}")
        return tooling
    for marker, (purpose, command) in PYPROJECT_MARKERS.items():
        if marker in snippet:
            tooling.append(
                {
                    "purpose": purpose,
                    "command": command,
                    "basis": f"pyproject.toml mentions {marker!r}",
                }
            )
    return tooling


def _scan_tree(
    root: str, max_files: int, warnings: list[str]
) -> dict[str, Any]:
    """Bounded walk collecting languages, frameworks, configs, test counts."""
    languages: dict[str, list[str]] = {}
    frameworks: list[dict[str, str]] = []
    tooling: list[dict[str, str]] = []
    build_configs: list[str] = []
    ci_configs: list[str] = []
    test_file_count = 0
    test_file_examples: list[str] = []
    files_scanned = 0
    truncated = False
    skipped_directories: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        for name in list(dirnames):
            if name in SKIPPED_DIRECTORIES:
                skipped_directories.append(name)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIPPED_DIRECTORIES and not name.startswith(".")
        )
        for filename in sorted(filenames):
            if files_scanned >= max_files:
                truncated = True
                break
            files_scanned += 1
            relative = os.path.relpath(os.path.join(dirpath, filename), root)
            relative_posix = relative.replace(os.sep, "/")

            if filename == "package.json":
                languages.setdefault("javascript", []).append("package.json")
                node_frameworks, node_tooling = _detect_node_frameworks(
                    Path(dirpath) / filename, warnings
                )
                frameworks.extend(node_frameworks)
                tooling.extend(node_tooling)
            elif filename == "pyproject.toml":
                languages.setdefault("python", []).append("pyproject.toml")
                tooling.extend(
                    _detect_python_tooling(Path(dirpath) / filename, warnings)
                )
            elif filename in CONFIG_LANGUAGES:
                for language in CONFIG_LANGUAGES[filename]:
                    languages.setdefault(language, []).append(filename)
                if filename != "Dockerfile":
                    build_configs.append(relative_posix)
            elif filename.endswith(".csproj"):
                languages.setdefault("csharp", []).append(relative_posix)

            if relative_posix.startswith(".github/workflows/") and filename.endswith(
                (".yml", ".yaml")
            ):
                ci_configs.append(relative_posix)

            matched_test = any(
                _match_test_pattern(filename, pattern)
                for pattern in TEST_FILE_PATTERNS
            )
            if matched_test:
                test_file_count += 1
                if len(test_file_examples) < 10:
                    test_file_examples.append(relative_posix)
        if truncated:
            break

    language_list = [
        {"name": name, "evidence": evidence, "basis": "observed"}
        for name, evidence in sorted(languages.items())
    ]
    return {
        "files_scanned": files_scanned,
        "scan_truncated": truncated,
        "skipped_directories": sorted(set(skipped_directories)),
        "languages": language_list,
        "frameworks": frameworks,
        "build_configs": build_configs[:50],
        "ci_configs": ci_configs[:50],
        "test_files_found": test_file_count,
        "test_file_examples": test_file_examples,
        "suggested_commands": tooling,
    }


def _match_test_pattern(filename: str, pattern: str) -> bool:
    """Small glob matcher for the fixed test-file patterns (no external deps)."""
    if pattern.startswith("test_") and pattern.endswith(".py"):
        return filename.startswith("test_") and filename.endswith(".py")
    if pattern == "*_test.py":
        return filename.endswith("_test.py")
    for suffix in (
        ".test.js", ".test.ts", ".test.jsx", ".test.tsx",
        ".spec.js", ".spec.ts", ".spec.jsx", ".spec.tsx",
    ):
        if pattern.endswith(suffix):
            return filename.endswith(suffix)
    return False


def inspect(root: str, max_files: int = DEFAULT_MAX_FILES) -> dict[str, Any]:
    """Produce the full inventory dict for *root*."""
    normalized = _resolve_target(root)
    warnings: list[str] = []

    scan = _scan_tree(normalized, max_files, warnings)
    if scan["scan_truncated"]:
        warnings.append(
            f"file scan truncated at {max_files} files; inventory may be incomplete"
        )
    if not scan["languages"]:
        warnings.append(
            "no language configuration files detected; the tree may be "
            "vendorless or empty"
        )

    git = _git_state(normalized, warnings)

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "root": normalized,
        "operating_system": platform.system(),
        "python_version": platform.python_version(),
        "git": git,
        "files_scanned": scan["files_scanned"],
        "scan_truncated": scan["scan_truncated"],
        "skipped_directories": scan["skipped_directories"],
        "languages": scan["languages"],
        "frameworks": scan["frameworks"],
        "build_configs": scan["build_configs"],
        "ci_configs": scan["ci_configs"],
        "test_files_found": scan["test_files_found"],
        "test_file_examples": scan["test_file_examples"],
        "suggested_commands": scan["suggested_commands"],
        "warnings": warnings,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only repository inventory for PatchProof. "
        "Prints JSON to stdout."
    )
    parser.add_argument("path", nargs="?", default=".", help="repository path")
    parser.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        help=f"maximum files to scan (default {DEFAULT_MAX_FILES})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_files < 1:
        print(
            json.dumps(
                {"valid": False, "error": "--max-files must be >= 1"},
                indent=2,
            )
        )
        return 2
    try:
        result = inspect(args.path, max_files=args.max_files)
    except TargetError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
