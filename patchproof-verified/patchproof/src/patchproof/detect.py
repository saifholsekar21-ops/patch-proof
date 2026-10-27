"""Project tooling detection for PatchProof.

Detects languages, frameworks, and candidate verification commands from
repository configuration files, then probes which candidate executables are
actually available. Detected commands are *suggestions*; availability probing
and user configuration decide what actually runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_READ_LIMIT = 64 * 1024
PROBE_TIMEOUT_S = 5

SKIPPED_DIRECTORIES = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "venv", ".venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", "target", ".next", ".nuxt", ".tox", ".nox",
    ".idea", ".vscode", "coverage",
}

CONFIG_LANGUAGES = {
    "pyproject.toml": ["python"],
    "requirements.txt": ["python"],
    "setup.py": ["python"],
    "setup.cfg": ["python"],
    "Pipfile": ["python"],
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
}


@dataclass
class CommandHint:
    purpose: str  # "test" | "lint" | "typecheck" | "deps"
    command: list[str]
    basis: str
    available: bool = False
    version: str | None = None


@dataclass
class ProjectFacts:
    root: str
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    hints: list[CommandHint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def hints_for(self, purpose: str) -> list[CommandHint]:
        return [hint for hint in self.hints if hint.purpose == purpose]


def _read_snippet(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(CONFIG_READ_LIMIT)
    except OSError:
        return None


def _probe(executable: str) -> tuple[bool, str | None]:
    """Check whether *executable* is on PATH and report its version string.

    Only --version/-V probing; never runs project code.
    """
    which = shutil.which(executable)
    if which is None:
        return False, None
    try:
        completed = subprocess.run(
            [which, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True, None
    output = (completed.stdout or completed.stderr or "").strip()
    if not output:
        return True, None
    return True, output.splitlines()[0][:200]


def _probe_module(python: str, module: str) -> tuple[bool, str | None]:
    """Probe a ``python -m <module>`` tool by asking the module for --version."""
    which = shutil.which(python)
    if which is None:
        return False, None
    try:
        completed = subprocess.run(
            [which, "-m", module, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True, None
    if completed.returncode != 0:
        return False, None
    output = (completed.stdout or completed.stderr or "").strip()
    return True, output.splitlines()[0][:200] if output else None


def _probe_hint(hint: CommandHint) -> tuple[bool, str | None]:
    """Probe tool availability for a command hint without running project code.

    ``python -m <module>`` hints probe the module itself; npm/npx hints probe
    only the runner (never a project script, and never npx's auto-install).
    """
    command = hint.command
    if len(command) >= 3 and command[0] in ("python", "python3", "py") and command[1] == "-m":
        return _probe_module(command[0], command[2])
    return _probe(command[0])


def _analyze_package_json(path: Path, facts: ProjectFacts) -> None:
    snippet = _read_snippet(path)
    if snippet is None:
        facts.warnings.append(f"could not read {path.name}")
        return
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError as exc:
        facts.warnings.append(
            f"{path.name} is not valid JSON (line {exc.lineno}); "
            "JavaScript tooling analysis skipped"
        )
        return
    if not isinstance(data, dict):
        return
    deps: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        content = data.get(section)
        if isinstance(content, dict):
            for key, value in content.items():
                if isinstance(key, str) and isinstance(value, str):
                    deps[key] = value
    for package in ("react", "vue", "angular", "@angular/core", "next", "svelte", "electron"):
        if package in deps:
            facts.frameworks.append(package)
    hints = facts.hints
    if isinstance(data.get("scripts"), dict):
        scripts = data["scripts"]
        for purpose, script in (("test", "test"), ("lint", "lint"), ("typecheck", "typecheck")):
            if isinstance(scripts.get(script), str):
                hints.append(
                    CommandHint(purpose, ["npm", "run", script], f"package.json script {script!r}")
                )
    if "jest" in deps and not any(h.purpose == "test" for h in hints):
        hints.append(CommandHint("test", ["npx", "jest"], "package.json devDependency jest"))
    if "eslint" in deps and not any(h.purpose == "lint" for h in hints):
        hints.append(
            CommandHint("lint", ["npx", "eslint", "."], "package.json devDependency eslint")
        )
    if "typescript" in deps and not any(h.purpose == "typecheck" for h in hints):
        hints.append(
            CommandHint(
                "typecheck",
                ["npx", "tsc", "--noEmit"],
                "package.json devDependency typescript",
            )
        )


def _analyze_pyproject(path: Path, hints: list[CommandHint], warnings: list[str]) -> None:
    snippet = _read_snippet(path)
    if snippet is None:
        warnings.append(f"could not read {path.name}")
        return
    if "pytest" in snippet:
        hints.append(
            CommandHint("test", ["python", "-m", "pytest", "-q"], "pyproject.toml mentions pytest")
        )
    if "ruff" in snippet:
        hints.append(
            CommandHint(
                "lint", ["python", "-m", "ruff", "check", "."], "pyproject.toml mentions ruff"
            )
        )
    if "mypy" in snippet:
        hints.append(
            CommandHint("typecheck", ["python", "-m", "mypy", "."], "pyproject.toml mentions mypy")
        )
    if "pip-audit" in snippet:
        hints.append(
            CommandHint("deps", ["python", "-m", "pip_audit"], "pyproject.toml mentions pip-audit")
        )


def detect_project(root: str) -> ProjectFacts:
    """Detect languages and tooling for the repository at *root* (read-only)."""
    facts = ProjectFacts(root=os.path.abspath(root))
    seen_files = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIPPED_DIRECTORIES and not name.startswith(".")
        )
        for filename in sorted(filenames):
            seen_files += 1
            if seen_files > 2000:
                facts.warnings.append("detection scan truncated at 2000 files")
                break
            path = Path(dirpath) / filename
            if filename == "package.json":
                facts.languages.append("javascript")
                _analyze_package_json(path, facts)
            elif filename == "pyproject.toml":
                facts.languages.append("python")
                _analyze_pyproject(path, facts.hints, facts.warnings)
            elif filename in CONFIG_LANGUAGES:
                for language in CONFIG_LANGUAGES[filename]:
                    facts.languages.append(language)
        if seen_files > 2000:
            break
    facts.languages = sorted(set(facts.languages))

    probed: list[CommandHint] = []
    for hint in facts.hints:
        available, version = _probe_hint(hint)
        hint.available = available
        hint.version = version
        probed.append(hint)
    facts.hints = probed

    if not facts.languages:
        facts.warnings.append(
            "no language configuration files detected; configure checks explicitly"
        )
    return facts
