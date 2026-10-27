"""Shared helpers for tests that need throwaway git repositories."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

GIT = shutil.which("git")


def init_repo(path: Path, *, branch: str = "main") -> str:
    """Create a repository with one committed file; return the initial commit sha."""
    if GIT is None:
        raise RuntimeError("git executable not found on PATH")
    (path / "tracked.txt").write_text("hello\n", encoding="utf-8")
    git(path, "init", "-q", "-b", branch)
    git(path, "config", "user.name", "PatchProof Tests")
    git(path, "config", "user.email", "tests@patchproof.invalid")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-q", "-m", "initial")
    return git(path, "rev-parse", "HEAD").stdout.strip()


def git(path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in *path* (fails the test on git errors)."""
    if GIT is None:
        raise RuntimeError("git executable not found on PATH")
    return subprocess.run(
        [GIT, *args],
        cwd=str(path),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
