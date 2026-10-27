"""Tests for report rendering (patchproof.render)."""

from __future__ import annotations

from patchproof.models import CheckResult, Report
from patchproof.render import render_markdown


def make_report(
    check: CheckResult, *, branch: str | None = None, detached: bool = False
) -> Report:
    return Report(
        patchproof_version="1.1.0",
        task_id="t1",
        task_description="desc",
        repository={
            "path": "example/project",
            "revision": None,
            "branch": branch,
            "dirty": False,
            "detached": detached,
        },
        selection_policy="none",
        checks=[check],
        overall_status="passed",
    )


def make_passed_check(stdout: str = "1 passed\n") -> CheckResult:
    return CheckResult(
        id="tests",
        category="tests",
        tool="pytest",
        command="pytest -q",
        status="passed",
        required=True,
        exit_code=0,
        stdout=stdout,
    )


def test_markdown_includes_every_evidence_line():
    check = make_passed_check(".... [100%]\n179 passed in 1.0s\n")
    markdown = render_markdown(make_report(check))
    assert ".... [100%]" in markdown
    assert "179 passed in 1.0s" in markdown


def test_markdown_labels_missing_branch_as_unknown():
    markdown = render_markdown(make_report(make_passed_check()))
    assert "branch: `unknown`" in markdown
    assert "branch: `detached`" not in markdown


def test_markdown_labels_detached_head():
    markdown = render_markdown(make_report(make_passed_check(), detached=True))
    assert "branch: `detached`" in markdown
