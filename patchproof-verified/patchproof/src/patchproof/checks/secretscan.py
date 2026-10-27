"""Internal secret-scanning check: scans repository files for credentials.

Regex-based scanning has documented limitations (see SECURITY.md); findings
report the *redacted* matching line as evidence, so the raw secret never
enters the report.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..models import Finding, Location
from ..secrets import iter_secret_matches, redact_text

SKIPPED_DIRECTORIES = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "venv", ".venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", "target", ".next", ".nuxt", ".tox", ".nox",
    ".idea", ".vscode", "coverage", ".turbo",
}

SKIPPED_FILENAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock"}


def _is_binary(header: bytes) -> bool:
    return b"\x00" in header


def scan_repository_secrets(
    root: str, max_files: int = 2000, max_file_bytes: int = 1_048_576
) -> list[Finding]:
    """Scan text files under *root* for credential patterns. Read-only.

    Returns deterministic (path, line)-ordered findings. Files that cannot
    be read are skipped silently; binary files and vendored directories are
    excluded.
    """
    findings: list[Finding] = []
    files_scanned = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIPPED_DIRECTORIES and not name.startswith(".")
        )
        for filename in sorted(filenames):
            if files_scanned >= max_files:
                return findings
            if filename in SKIPPED_FILENAMES:
                continue
            path = Path(dirpath) / filename
            files_scanned += 1
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size == 0 or size > max_file_bytes:
                continue
            try:
                with open(path, "rb") as handle:
                    header = handle.read(8192)
                if _is_binary(header):
                    continue
                text = header.decode("utf-8", errors="replace")
            except OSError:
                continue
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for kind, _match in iter_secret_matches(line):
                    findings.append(
                        Finding(
                            severity="high",
                            title=f"possible {kind} in {relative}",
                            description=(
                                "Pattern-based credential detection. This is a "
                                "candidate match, not proof of a live secret; "
                                "verify manually and rotate anything exposed."
                            ),
                            evidence=[f"{relative}:{line_number}: {redact_text(line).strip()}"],
                            locations=[Location(file=relative, line=line_number)],
                        )
                    )
    return findings
