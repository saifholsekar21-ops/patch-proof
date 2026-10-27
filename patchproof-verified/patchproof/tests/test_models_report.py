"""Tests for report models and the overall-status policy (patchproof.models)."""

from __future__ import annotations

from patchproof.models import CheckResult, CheckStatus, Report, compute_overall
from patchproof.validate import validate_report


def make_check(
    status: CheckStatus, *, required: bool = True, identifier: str = "c1"
) -> CheckResult:
    return CheckResult(
        id=identifier,
        category="tests",
        tool="pytest",
        command="pytest -q",
        status=status,
        required=required,
    )


def test_overall_status_policy():
    passed = make_check("passed")
    failed = make_check("failed")
    error = make_check("error")
    unverified = make_check("unverified")
    skipped = make_check("skipped")
    optional_failed = make_check("failed", required=False)

    assert compute_overall([passed]) == "passed"
    assert compute_overall([passed, optional_failed]) == "passed"
    assert compute_overall([passed, failed]) == "failed"
    assert compute_overall([passed, error]) == "error"
    assert compute_overall([passed, unverified]) == "unverified"
    assert compute_overall([passed, skipped]) == "unverified"
    assert compute_overall([failed, error]) == "failed"
    assert compute_overall([error, unverified]) == "error"
    assert compute_overall([]) == "unverified"
    assert compute_overall([optional_failed]) == "unverified"


def test_schema_entry_for_running_checks_has_evidence():
    passed = CheckResult(
        id="c1",
        category="tests",
        tool="pytest",
        command="pytest -q",
        status="passed",
        required=True,
        exit_code=0,
        duration_s=1.0,
        stdout="1 passed\n",
    )
    entry = passed.to_schema_entry()
    assert entry["status"] == "passed"
    assert entry["required"] is True
    assert entry["evidence"] == ["1 passed"]
    assert entry["summary"] == ""


def test_schema_entry_for_skipped_check_has_reason():
    skipped = CheckResult(
        id="c2",
        category="lint",
        tool="ruff",
        command="ruff check",
        status="skipped",
        required=False,
        reason="ruff not installed",
    )
    entry = skipped.to_schema_entry()
    assert entry["reason"] == "ruff not installed"
    assert "evidence" not in entry


def test_evidence_lines_capped_at_five():
    result = CheckResult(
        id="c1",
        category="tests",
        tool="pytest",
        command="pytest -q",
        status="failed",
        stderr="\n".join(f"line {index}" for index in range(10)),
    )
    assert len(result.evidence_lines()) == 5
    assert result.evidence_lines()[0] == "line 0"


def test_report_serializes_to_valid_schema():
    report = Report(
        patchproof_version="0.1.0",
        task_id="t1",
        task_description="desc",
        repository={"path": "example/project", "revision": None, "branch": None, "dirty": False},
        selection_policy="working",
        checks=[
            CheckResult(
                id="c1",
                category="tests",
                tool="pytest",
                command="pytest -q",
                status="passed",
                required=True,
                exit_code=0,
            )
        ],
        overall_status="passed",
    )
    data = report.to_schema_dict()
    result = validate_report(data)
    assert result["valid"], result["errors"]
    assert data["schema_version"] == "1.1"
    assert data["changes"] == []
