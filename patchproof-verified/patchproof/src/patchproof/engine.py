"""Verification orchestration: run selected checks and aggregate results."""

from __future__ import annotations

from .checks import build_check_specs
from .checks.base import CheckSpec, run_check
from .checks.secretscan import scan_repository_secrets
from .config import PatchProofConfig
from .detect import detect_project
from .models import CheckResult, ExecutionError, Report, compute_overall
from .repo import ChangeSet, repo_info
from .validate import validate_report

CATEGORY_ORDER = ("tests", "lint", "typecheck", "secrets", "deps", "custom")


class VerificationError(Exception):
    """Verification could not start (bad path, git failure, ...)."""


def run_verification(
    root: str,
    config: PatchProofConfig,
    change_set: ChangeSet,
    task_id: str = "patchproof-run",
    task_description: str = "",
) -> Report:
    """Run all configured checks against *root*. Read-only with respect to
    tracked files; check processes may read the repository.

    Raises VerificationError only for environment-level failures detected
    before checks run. Per-check failures are captured in the report.
    """
    from . import __version__

    facts = detect_project(root)
    specs = build_check_specs(config, facts, root)
    results: list[CheckResult] = []
    execution_errors: list[ExecutionError] = []

    by_category: dict[str, CheckSpec] = {spec.category: spec for spec in specs}

    for category in CATEGORY_ORDER:
        if category == "secrets":
            if config.secrets.enabled:
                results.append(
                    _run_secrets_check(root, config, category in config.checks.required)
                )
            continue
        if category == "custom":
            for spec in [s for s in specs if s.category == "custom"]:
                results.append(_execute(spec, config, execution_errors))
            continue
        resolved = by_category.get(category)
        if resolved is None:
            if category in (set(config.checks.required) | set(config.checks.optional)):
                results.append(_unresolved_result(category, config))
            continue
        results.append(_execute(resolved, config, execution_errors))

    info = repo_info(root)
    repository = {
        "path": root,
        "revision": info.head_revision,
        "branch": info.branch,
        "dirty": info.dirty,
        "detached": info.detached,
    }

    limitations: list[str] = list(change_set.notes)
    limitations.extend(facts.warnings)
    limitations.append(
        "checks execute with the invoking user's privileges; no sandboxing is "
        "performed (run PatchProof inside an isolated environment for untrusted code)"
    )

    skipped_checks: list[dict[str, str]] = []  # legacy view; statuses live on checks

    findings = [finding for result in results for finding in result.findings]

    report = Report(
        patchproof_version=__version__,
        task_id=task_id,
        task_description=task_description or f"patchproof verification of {root}",
        repository=repository,
        selection_policy=change_set.selection,
        changed_files=change_set.to_report_entries(),
        checks=results,
        findings=findings,
        skipped_checks=skipped_checks,
        execution_errors=execution_errors,
        overall_status=compute_overall(results),
        limitations=limitations,
        conclusion="",
    )
    _assert_self_valid(report)
    return report


def _execute(
    spec, config: PatchProofConfig, execution_errors: list[ExecutionError]
) -> CheckResult:
    try:
        return run_check(spec, config.limits.output_limit_bytes)
    except Exception as exc:  # defensive: a check must never take down the run
        execution_errors.append(ExecutionError(check_id=spec.id, message=str(exc)))
        return CheckResult(
            id=spec.id,
            category=spec.category,
            tool=spec.tool,
            command=spec.display_command,
            status="error",
            required=spec.required,
            reason=f"internal execution failure: {exc}",
        )


def _unresolved_result(category: str, config: PatchProofConfig) -> CheckResult:
    required = category in config.checks.required
    return CheckResult(
        id=category,
        category=category,
        tool=category,
        command="(not configured)",
        status="unverified",
        required=required,
        reason=(
            f"no {category} command detected and no [checks.{category}] override "
            "configured"
        ),
    )


def _run_secrets_check(root: str, config: PatchProofConfig, required: bool) -> CheckResult:
    findings = scan_repository_secrets(
        root,
        max_files=config.secrets.max_files,
        max_file_bytes=config.secrets.max_file_bytes,
    )
    if findings:
        stderr = "\n".join(finding.evidence[0] for finding in findings[:5])
    else:
        stderr = "no credential patterns found in scanned files"
    return CheckResult(
        id="secrets",
        category="secrets",
        tool="patchproof-secrets",
        command="internal repository scan (regex patterns; see SECURITY.md)",
        status="failed" if findings else "passed",
        required=required,
        findings=findings,
        stderr=stderr,
    )


def _assert_self_valid(report: Report) -> None:
    """Defensive check: PatchProof must never emit an invalid report."""
    result = validate_report(report.to_schema_dict())
    if not result["valid"]:
        details = "; ".join(
            f"{entry['path']}: {entry['message']}" for entry in result["errors"][:5]
        )
        raise VerificationError(f"generated report failed self-validation: {details}")
