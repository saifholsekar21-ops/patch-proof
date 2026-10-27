"""Tests for the read-only git integration layer (patchproof.repo)."""

from __future__ import annotations

import shutil

import gitutil
import pytest

from patchproof.repo import (
    GitError,
    GitUnavailable,
    RevisionError,
    changed_files,
    repo_info,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def make_states(tmp_path):
    """Repository with a staged add, a staged delete, an unstaged edit, and an untracked file."""
    root = tmp_path / "repo"
    root.mkdir()
    initial = gitutil.init_repo(root)
    (root / "gone.txt").write_text("bye\n", encoding="utf-8")
    gitutil.git(root, "add", "gone.txt")
    gitutil.git(root, "commit", "-q", "-m", "add gone")
    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (root / "notes.md").write_text("new file\n", encoding="utf-8")
    gitutil.git(root, "add", "notes.md")
    (root / "gone.txt").unlink()
    gitutil.git(root, "add", "gone.txt")
    (root / "extra.txt").write_text("untracked\n", encoding="utf-8")
    return root, initial


def test_working_tree_statuses_are_porcelain_letters(tmp_path):
    root, _initial = make_states(tmp_path)
    change_set = changed_files(str(root), selection="working")
    assert sorted(change_set.staged) == [("gone.txt", "D"), ("notes.md", "A")]
    assert change_set.unstaged == [("tracked.txt", "M")]
    assert change_set.untracked == ["extra.txt"]


def test_report_entries_carry_real_status_and_origin(tmp_path):
    root, _initial = make_states(tmp_path)
    entries = changed_files(str(root), selection="working").to_report_entries()
    by_path = {entry["path"]: entry for entry in entries}
    assert by_path["notes.md"] == {"path": "notes.md", "status": "A", "origin": "staged"}
    assert by_path["tracked.txt"] == {
        "path": "tracked.txt",
        "status": "M",
        "origin": "unstaged",
    }
    assert by_path["extra.txt"] == {
        "path": "extra.txt",
        "status": "U",
        "origin": "untracked",
    }
    assert by_path["gone.txt"] == {"path": "gone.txt", "status": "D", "origin": "staged"}


def test_single_category_selections(tmp_path):
    root, _initial = make_states(tmp_path)

    staged = changed_files(str(root), selection="staged")
    assert sorted(staged.staged) == [("gone.txt", "D"), ("notes.md", "A")]
    assert staged.unstaged == []
    assert staged.untracked == []

    unstaged = changed_files(str(root), selection="unstaged")
    assert unstaged.staged == []
    assert unstaged.unstaged == [("tracked.txt", "M")]
    assert unstaged.untracked == []

    untracked = changed_files(str(root), selection="untracked")
    assert untracked.staged == []
    assert untracked.unstaged == []
    assert untracked.untracked == ["extra.txt"]


def test_untracked_files_are_not_claimed_as_diff(tmp_path):
    root, _initial = make_states(tmp_path)
    change_set = changed_files(str(root), selection="working")
    assert any("not part of any diff" in note for note in change_set.notes)


def test_index_rename_parsed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    gitutil.git(root, "mv", "tracked.txt", "renamed.txt")
    change_set = changed_files(str(root), selection="staged")
    assert change_set.staged == [("renamed.txt", "R")]


def test_all_paths_deduplicates(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    (root / "tracked.txt").write_text("staged change\n", encoding="utf-8")
    gitutil.git(root, "add", "tracked.txt")
    (root / "tracked.txt").write_text("unstaged change\n", encoding="utf-8")
    change_set = changed_files(str(root), selection="working")
    assert change_set.all_paths == ["tracked.txt"]


def test_committed_range_lists_diff_entries(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    initial = gitutil.init_repo(root)
    (root / "second.txt").write_text("second\n", encoding="utf-8")
    gitutil.git(root, "add", "second.txt")
    gitutil.git(root, "commit", "-q", "-m", "second")
    head = gitutil.git(root, "rev-parse", "HEAD").stdout.strip()

    change_set = changed_files(str(root), selection="committed", base=initial, head=head)
    assert [entry.path for entry in change_set.committed] == ["second.txt"]
    entry = change_set.committed[0]
    assert entry.status == "A"
    assert entry.additions == 1
    assert change_set.to_report_entries()[0]["origin"] == f"committed {initial}..{head}"


def test_all_includes_working_and_committed(tmp_path):
    root, initial = make_states(tmp_path)
    change_set = changed_files(str(root), selection="all", base=initial, head="HEAD")
    assert change_set.untracked == ["extra.txt"]
    assert [entry.path for entry in change_set.committed] == ["gone.txt"]


def test_empty_committed_range_is_not_an_error(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    initial = gitutil.init_repo(root)
    change_set = changed_files(str(root), selection="committed", base=initial, head=initial)
    assert change_set.committed == []
    assert any("no committed changes" in note for note in change_set.notes)


def test_invalid_revisions_raise_revision_error(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    initial = gitutil.init_repo(root)
    with pytest.raises(RevisionError):
        changed_files(str(root), selection="committed", base="deadbeefdeadbeef", head=initial)
    with pytest.raises(RevisionError):
        changed_files(str(root), selection="committed", base=initial, head="deadbeefdeadbeef")


@pytest.mark.parametrize(
    ("base", "head"),
    [("--output=stolen.diff", "HEAD"), ("HEAD", "--output=stolen.diff")],
)
def test_option_like_revisions_are_rejected(tmp_path, base, head):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    with pytest.raises(GitError, match="must not start with"):
        changed_files(str(root), selection="committed", base=base, head=head)
    assert not (root / "stolen.diff").exists()


def test_committed_diff_disables_repository_diff_drivers(tmp_path, monkeypatch):
    import patchproof.repo as repo_module

    commands = []

    def fake_run(_root, args, timeout=15):
        commands.append(list(args))
        return 0, "", ""

    monkeypatch.setattr(repo_module, "_verify_revision", lambda _root, _revision: None)
    monkeypatch.setattr(repo_module, "_run_git", fake_run)
    repo_module._committed_diff(str(tmp_path), "base", "head")
    diff_commands = [args for args in commands if args and args[0] == "diff"]
    assert len(diff_commands) == 2
    for args in diff_commands:
        assert "--no-ext-diff" in args
        assert "--no-textconv" in args


def test_committed_selection_requires_both_revisions(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    with pytest.raises(GitError, match="requires both"):
        changed_files(str(root), selection="committed")


def test_none_selection_collects_nothing(tmp_path):
    root, _initial = make_states(tmp_path)
    change_set = changed_files(str(root), selection="none")
    assert change_set.staged == []
    assert change_set.unstaged == []
    assert change_set.untracked == []
    assert change_set.committed == []


def test_unknown_selection_raises(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    with pytest.raises(GitError, match="unknown change selection"):
        changed_files(str(root), selection="bogus")


def test_non_repository_directory_raises(tmp_path):
    with pytest.raises(GitError, match="not a git repository"):
        changed_files(str(tmp_path), selection="working")


def test_missing_directory_raises(tmp_path):
    with pytest.raises(GitError, match="not a directory"):
        changed_files(str(tmp_path / "missing"), selection="working")


def test_git_status_disables_optional_locks_and_fsmonitor(tmp_path, monkeypatch):
    import patchproof.repo as repo_module

    captured = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        return Result()

    monkeypatch.setattr(repo_module.subprocess, "run", fake_run)
    repo_module._working_tree_paths(str(tmp_path))
    assert captured["command"] == [
        "git",
        "-c",
        "core.fsmonitor=false",
        "status",
        "--porcelain",
    ]
    assert captured["env"]["GIT_OPTIONAL_LOCKS"] == "0"


def test_git_unavailable_propagates(tmp_path, monkeypatch):
    import patchproof.repo as repo_module

    def fake_run(*_args, **_kwargs):
        raise GitUnavailable("git executable not found on PATH")

    monkeypatch.setattr(repo_module, "_run_git", fake_run)
    with pytest.raises(GitUnavailable):
        changed_files(str(tmp_path), selection="working")


def test_dirty_flag_reflects_working_tree(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    assert repo_info(str(root)).dirty is False
    (root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    assert repo_info(str(root)).dirty is True


def test_detached_head_reported(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    initial = gitutil.init_repo(root)
    gitutil.git(root, "checkout", "-q", "--detach")
    info = repo_info(str(root))
    assert info.detached is True
    assert info.branch is None
    assert info.head_revision == initial


def test_shallow_clone_detected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    clone = tmp_path / "clone"
    url = f"file:///{root.resolve().as_posix()}"
    gitutil.git(tmp_path, "clone", "-q", "--depth", "1", url, str(clone))
    info = repo_info(str(clone))
    assert info.is_repository is True
    assert info.shallow is True
    assert info.head_revision


def test_non_git_repo_info_is_graceful(tmp_path):
    info = repo_info(str(tmp_path))
    assert info.is_repository is False
    assert info.branch is None
    assert info.head_revision is None
