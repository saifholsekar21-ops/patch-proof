"""Pydantic models for PatchProof runs, checks, and reports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["passed", "failed", "skipped", "error", "unverified"]
Severity = Literal["critical", "high", "medium", "low", "info"]
OverallStatus = Literal["passed", "failed", "error", "unverified"]
VerificationStatus = Literal["verified", "unverified", "proposed"]

CHECK_CATEGORIES = ("tests", "lint", "typecheck", "secrets", "deps", "custom")


class Location(BaseModel):
    file: str
    line: int | None = None
    column: int | None = None


class Finding(BaseModel):
    severity: Severity = "info"
    title: str
    description: str = ""
    evidence: list[str] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)


class CheckResult(BaseModel):
    id: str
    category: str
    tool: str
    command: str
    status: CheckStatus
    required: bool = True
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_s: float | None = None
    exit_code: int | None = None
    # Captured output is bounded at capture time and redacted before storage.
    stdout: str = ""
    stderr: str = ""
    findings: list[Finding] = Field(default_factory=list)
    reason: str | None = None

    def evidence_lines(self, limit: int = 5) -> list[str]:
        """Representative captured-output lines for report evidence."""
        lines: list[str] = []
        for line in (self.stderr or "").splitlines():
            if line.strip():
                lines.append(line)
                if len(lines) >= limit:
                    return lines
        for line in (self.stdout or "").splitlines():
            if line.strip():
                lines.append(line)
                if len(lines) >= limit:
                    return lines
        return lines

    def to_schema_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": self.id,
            "tool": self.tool,
            "category": self.category,
            "command": self.command,
            "status": self.status,
            "required": self.required,
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
        }
        if self.status in ("passed", "failed", "error"):
            entry["summary"] = (
                self.findings[0].title if self.findings else self.reason or ""
            )
            evidence = self.evidence_lines()
            if not evidence and self.reason:
                # A check that never executed (missing tool, timeout) has no
                # output; the reason is the only evidence, and the schema
                # requires evidence or an exit code for running statuses.
                evidence = [self.reason]
            entry["evidence"] = evidence
        if self.status in ("skipped", "unverified") or self.reason:
            entry["reason"] = self.reason or ""
        return entry


class ExecutionError(BaseModel):
    check_id: str
    message: str


class Report(BaseModel):
    """A schema-1.1 verification report."""

    schema_version: Literal["1.1"] = "1.1"
    patchproof_version: str
    task_id: str
    task_description: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    repository: dict[str, Any]
    selection_policy: str
    changed_files: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[CheckResult]
    findings: list[Finding] = Field(default_factory=list)
    skipped_checks: list[dict[str, str]] = Field(default_factory=list)
    execution_errors: list[ExecutionError] = Field(default_factory=list)
    overall_status: OverallStatus
    limitations: list[str] = Field(default_factory=list)
    conclusion: str = ""

    def to_schema_dict(self) -> dict[str, Any]:
        """Serialize into the documented schema-1.1 JSON shape."""
        return {
            "schema_version": self.schema_version,
            "patchproof_version": self.patchproof_version,
            "task_id": self.task_id,
            "task_description": self.task_description,
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
            "repository": self.repository,
            "selection_policy": self.selection_policy,
            "changed_files": self.changed_files,
            "findings": [
                {
                    "id": f"F-{index + 1:03d}",
                    "severity": finding.severity,
                    "status": "open",
                    "title": finding.title,
                    "description": finding.description,
                    "evidence": finding.evidence,
                    "locations": [
                        location.model_dump(exclude_none=True)
                        for location in finding.locations
                    ],
                }
                for index, finding in enumerate(self.findings)
            ],
            "checks": [check.to_schema_entry() for check in self.checks],
            "skipped_checks": self.skipped_checks,
            "execution_errors": [
                {"check_id": error.check_id, "message": error.message}
                for error in self.execution_errors
            ],
            "overall_status": self.overall_status,
            "limitations": self.limitations,
            "conclusion": self.conclusion,
            # Schema 1.0 compatibility: empty change list; fix changes are
            # not something a verification run can claim.
            "changes": [],
        }


def compute_overall(results: list[CheckResult]) -> OverallStatus:
    """Overall status policy.

    - ``failed``     if any required check failed.
    - ``error``      else if any required check could not execute reliably
                     (status error, including a missing required tool).
    - ``unverified`` else if any required check is unverified or skipped, or
                     no required checks were configured at all.
    - ``passed``     only when every required check passed.

    Optional checks never drive the overall result down; they remain visible
    in the report.
    """
    required = [result for result in results if result.required]
    if any(result.status == "failed" for result in required):
        return "failed"
    if any(result.status == "error" for result in required):
        return "error"
    if not required or any(
        result.status in ("unverified", "skipped") for result in required
    ):
        return "unverified"
    return "passed"
