"""Safe, read-only Git integration for PatchProof.

All git access goes through subprocess argument arrays (never shell=True).
Only read commands are used: this module cannot modify tracked files, stage,
commit, or rewrite history. Timeouts apply to every invocation.

Change selection is explicit:

- ``working`` (default): staged + unstaged + untracked entries. Untracked
  files are recorded separately and are never claimed to be part of a diff,
  because no diff exists for them.
- ``staged`` / ``unstaged`` / ``untracked``: single categories.
- ``committed``: files changed between ``--base`` and ``--head`` (diff
  metadata only; requires both revisions).
- ``all``: working-tree categories plus the ``base..head`` committed range.
- ``none``: no change analysis (used for whole-repository verification).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field

DEFAULT_GIT_TIMEOUT_S = 15

SELECTIONS = ("working", "staged", "unstaged", "untracked", "committed", "all", "none")


class GitError(Exception):
    """A git operation failed for an environmental or input reason."""


class GitUnavailable(GitError):
    """The git executable is not on PATH."""


class RevisionError(GitError):
    """A requested revision does not exist or cannot be resolved."""


@dataclass
class RepoInfo:
    root: str
    is_repository: bool
    branch: str | None = None
    head_revision: str | None = None
    dirty: bool | None = None
    shallow: bool = False
    detached: bool = False


@dataclass
class DiffEntry:
    path: str
    status: str  # A, M, D, R, C, T, U, X
    old_path: str | None = None
    additions: int | None = None
    deletions: int | None = None
    binary: bool = False


@dataclass
class ChangeSet:
    selection: str
    # (path, porcelain-status) pairs: the index flag for staged entries and
    # the worktree flag for unstaged entries.
    staged: list[tuple[str, str]] = field(default_factory=list)
    unstaged: list[tuple[str, str]] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    committed: list[DiffEntry] = field(default_factory=list)
    base: str | None = None
    head: str | None = None
    # Explanatory notes attached by the caller (e.g. "untracked files were not
    # part of any diff"). Always included in reports.
    notes: list[str] = field(default_factory=list)

    @property
    def all_paths(self) -> list[str]:
        """Every examined path, in a deterministic order, deduplicated."""
        seen: dict[str, None] = {}
        for entry in self.committed:
            seen.setdefault(entry.path, None)
            if entry.old_path and entry.old_path != entry.path:
                seen.setdefault(entry.old_path, None)
        for name, _status in self.staged + self.unstaged:
            seen.setdefault(name, None)
        for name in self.untracked:
            seen.setdefault(name, None)
        return list(seen)

    def to_report_entries(self) -> list[dict[str, object]]:
        """Schema-1.1 changed_files entries."""
        entries: list[dict[str, object]] = []
        for name, status in self.staged:
            entries.append({"path": name, "status": status, "origin": "staged"})
        for name, status in self.unstaged:
            entries.append({"path": name, "status": status, "origin": "unstaged"})
        for name in self.untracked:
            entries.append({"path": name, "status": "U", "origin": "untracked"})
        for diff in self.committed:
            entry: dict[str, object] = {
                "path": diff.path,
                "status": diff.status,
                "origin": f"committed {self.base}..{self.head}",
            }
            if diff.old_path:
                entry["old_path"] = diff.old_path
            if diff.additions is not None:
                entry["additions"] = diff.additions
            if diff.deletions is not None:
                entry["deletions"] = diff.deletions
            entries.append(entry)
        return entries


def _run_git(
    root: str, args: Sequence[str], timeout: int = DEFAULT_GIT_TIMEOUT_S
) -> tuple[int, str, str]:
    """Run a read-only git command with an argument array. Never uses a shell.

    ``GIT_OPTIONAL_LOCKS=0`` keeps commands such as ``git status`` from
    refreshing and rewriting the index as a side effect.
    """
    command = ["git", *args]
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError as exc:
        raise GitUnavailable("git executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    except OSError as exc:
        raise GitError(f"git {' '.join(args)} failed: {exc}") from exc


def is_git_repository(root: str) -> bool:
    returncode, _out, _err = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    return returncode == 0


def repo_info(root: str) -> RepoInfo:
    """Collect repository identity facts. Never raises GitUnavailable."""
    info = RepoInfo(root=root, is_repository=False)
    try:
        info.is_repository = is_git_repository(root)
    except GitUnavailable:
        return info
    if not info.is_repository:
        return info

    returncode, stdout, _err = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if returncode == 0:
        branch = stdout.strip()
        if branch == "HEAD":
            info.detached = True
        else:
            info.branch = branch

    returncode, stdout, _err = _run_git(root, ["rev-parse", "HEAD"])
    if returncode == 0:
        info.head_revision = stdout.strip()

    returncode, stdout, _err = _run_git(root, ["rev-parse", "--is-shallow-repository"])
    info.shallow = returncode == 0 and stdout.strip() == "true"

    returncode, stdout, _err = _run_git(root, ["status", "--porcelain"])
    if returncode == 0:
        info.dirty = bool(stdout.strip())
    return info


def _verify_revision(root: str, revision: str) -> None:
    returncode, _out, _err = _run_git(
        root, ["rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"]
    )
    if returncode != 0:
        raise RevisionError(
            f"revision {revision!r} cannot be resolved to a commit in this repository"
        )


def _working_tree_paths(
    root: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Return (staged, unstaged, untracked); staged/unstaged carry the
    porcelain status letter of their index/worktree flag."""
    staged: list[tuple[str, str]] = []
    unstaged: list[tuple[str, str]] = []
    untracked: list[str] = []
    returncode, stdout, _err = _run_git(
        root, ["-c", "core.fsmonitor=false", "status", "--porcelain"]
    )
    if returncode != 0:
        raise GitError("git status failed; cannot determine working-tree changes")
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        index_flag, worktree_flag = line[0], line[1]
        raw_path = line[3:].strip('"')
        # Porcelain v1 spells renames as "old -> new" in the path field.
        path = raw_path.split(" -> ", 1)[-1] if " -> " in raw_path else raw_path
        if index_flag == "?":
            untracked.append(path)
            continue
        if index_flag in "MADRC":
            staged.append((path, index_flag))
        if worktree_flag in "MD":
            unstaged.append((path, worktree_flag))
    staged.sort()
    unstaged.sort()
    untracked.sort()
    return staged, unstaged, untracked


def _committed_diff(root: str, base: str, head: str) -> list[DiffEntry]:
    _verify_revision(root, base)
    _verify_revision(root, head)

    returncode, stdout, stderr = _run_git(
        root,
        ["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-M", base, head],
    )
    if returncode != 0:
        raise GitError(f"git diff --name-status {base} {head} failed: {stderr.strip()}")
    name_status = _parse_name_status(stdout)

    returncode, stdout, _err = _run_git(
        root, ["diff", "--no-ext-diff", "--no-textconv", "--numstat", base, head]
    )
    numstat: dict[str, tuple[int | None, int | None, bool]] = {}
    if returncode == 0:
        for line in stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            adds, dels, path = parts
            binary = adds == "-" and dels == "-"
            numstat[path] = (
                None if binary else int(adds),
                None if binary else int(dels),
                binary,
            )

    entries: list[DiffEntry] = []
    for status, old_path, path in name_status:
        stats = numstat.get(path, (None, None, False))
        entries.append(
            DiffEntry(
                path=path,
                status=status,
                old_path=old_path,
                additions=stats[0],
                deletions=stats[1],
                binary=stats[2],
            )
        )
    return entries


def _parse_name_status(stdout: str) -> list[tuple[str, str | None, str]]:
    """Parse git diff --name-status output into (status, old_path, path)."""
    parsed: list[tuple[str, str | None, str]] = []
    for line in stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        code = parts[0]
        status = code[0]
        if status in ("R", "C") and len(parts) >= 3:
            parsed.append((status, parts[1], parts[2]))
        elif len(parts) >= 2:
            parsed.append((status, None, parts[1]))
    return parsed


def changed_files(
    root: str,
    selection: str = "working",
    base: str | None = None,
    head: str | None = None,
) -> ChangeSet:
    """Collect the change set for *selection* without modifying anything.

    Raises GitUnavailable when git is missing, RevisionError for unresolvable
    revisions, and GitError for other failures. Empty diffs yield empty
    collections (not errors).
    """
    if selection not in SELECTIONS:
        raise GitError(
            f"unknown change selection {selection!r}; expected one of "
            + ", ".join(SELECTIONS)
        )
    if not os.path.isdir(root):
        raise GitError(f"repository path is not a directory: {root!r}")
    if not is_git_repository(root):
        raise GitError(f"{root!r} is not a git repository")

    needs_range = selection in ("committed", "all")
    base_range: str | None = None
    head_range: str | None = None
    if needs_range:
        if not base or not head:
            raise GitError(
                f"change selection {selection!r} requires both --base and --head revisions"
            )
        for label, revision in (("--base", base), ("--head", head)):
            # Revisions are positional git arguments; a leading dash would be
            # parsed as an option (some of which can write files).
            if revision.startswith("-"):
                raise GitError(f"{label} revision must not start with '-': {revision!r}")
        base_range = base
        head_range = head

    result = ChangeSet(selection=selection, base=base, head=head)
    want_working = selection in ("working", "staged", "unstaged", "untracked", "all")

    if want_working:
        staged, unstaged, untracked = _working_tree_paths(root)
        if selection in ("working", "staged", "all"):
            result.staged = staged
        if selection in ("working", "unstaged", "all"):
            result.unstaged = unstaged
        if selection in ("working", "untracked", "all"):
            result.untracked = untracked
        if result.untracked:
            result.notes.append(
                f"{len(result.untracked)} untracked file(s) recorded; untracked files "
                "are not part of any diff and were listed from `git status --porcelain`"
            )

    if base_range is not None and head_range is not None:
        result.committed = _committed_diff(root, base_range, head_range)
        if not result.committed:
            result.notes.append(f"no committed changes between {base_range} and {head_range}")
    return result
