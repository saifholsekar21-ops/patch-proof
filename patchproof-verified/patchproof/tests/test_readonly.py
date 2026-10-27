"""Read-only guarantee: verification must not modify the repository."""

from __future__ import annotations

import shutil

import gitutil
import pytest

from patchproof import cli

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def test_verify_leaves_repository_untouched(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    (root / "extra.txt").write_text("untracked\n", encoding="utf-8")
    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    gitutil.git(root, "add", "tracked.txt")

    before_status = gitutil.git(root, "status", "--porcelain").stdout
    before_head = gitutil.git(root, "rev-parse", "HEAD").stdout
    before_reflog = gitutil.git(root, "reflog", "--format=%h").stdout
    before_files = sorted(path.name for path in root.iterdir())

    config = tmp_path / "cfg.toml"
    config.write_text(
        '[checks]\nrequired = ["secrets"]\noptional = []\n', encoding="utf-8"
    )
    code = cli.main(
        ["verify", str(root), "--select", "working", "--config", str(config)]
    )
    assert code == cli.EXIT_PASSED
    capsys.readouterr()

    assert gitutil.git(root, "status", "--porcelain").stdout == before_status
    assert gitutil.git(root, "rev-parse", "HEAD").stdout == before_head
    assert gitutil.git(root, "reflog", "--format=%h").stdout == before_reflog
    assert sorted(path.name for path in root.iterdir()) == before_files
