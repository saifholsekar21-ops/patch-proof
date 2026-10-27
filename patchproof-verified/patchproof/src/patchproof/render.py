"""Report rendering: JSON (schema 1.1), Markdown, and console text."""

from __future__ import annotations

import json

from .models import Report
from .secrets import redact_report

_STATUS_MARK = {
    "passed": "PASS",
    "failed": "FAIL",
    "skipped": "SKIP",
    "error": "ERROR",
    "unverified": "UNVERIFIED",
}


def render_json(report: Report, redact: bool = False) -> str:
    """Serialize the report to schema-1.1 JSON."""
    data = report.to_schema_dict()
    if redact:
        data = redact_report(data)
    return json.dumps(data, indent=2) + "\n"


def render_markdown(report: Report) -> str:
    """Human-readable Markdown rendering of the report."""
    lines: list[str] = []
    lines.append("# PatchProof verification report")
    lines.append("")
    lines.append(f"- Task: `{report.task_id}` — {report.task_description}")
    lines.append(f"- PatchProof: `{report.patchproof_version}`")
    lines.append(f"- Generated: {report.generated_at.isoformat(timespec='seconds')}")
    lines.append(f"- Overall status: **{report.overall_status}**")
    lines.append("")
    repo = report.repository
    branch_label = repo.get("branch") or (
        "detached" if repo.get("detached") else "unknown"
    )
    lines.append("## Repository")
    lines.append("")
    lines.append(
        f"- Path: `{repo.get('path', '?')}` · revision: `{repo.get('revision') or 'unknown'}`"
        f" · branch: `{branch_label}`"
        f" · dirty: {repo.get('dirty')}"
    )
    lines.append(f"- Change selection: `{report.selection_policy}`")
    if report.changed_files:
        lines.append("")
        lines.append("### Examined files")
        lines.append("")
        lines.append("| Path | Status | Origin | +/− |")
        lines.append("|------|--------|--------|-----|")
        for entry in report.changed_files:
            adds = entry.get("additions")
            dels = entry.get("deletions")
            diffstat = (
                f"+{adds}/-{dels}" if adds is not None and dels is not None else ""
            )
            lines.append(
                f"| `{entry.get('path', '')}` | {entry.get('status', '')} | "
                f"{entry.get('origin', '')} | {diffstat} |"
            )
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| ID | Category | Status | Exit | Duration | Tool |")
    lines.append("|----|----------|--------|------|----------|------|")
    for check in report.checks:
        exit_code = check.exit_code if check.exit_code is not None else "-"
        duration = f"{check.duration_s:g}s" if check.duration_s is not None else "-"
        required = " (required)" if check.required else ""
        lines.append(
            f"| {check.id} | {check.category}{required} | {check.status} | "
            f"{exit_code} | {duration} | {check.tool} |"
        )
    lines.append("")
    for check in report.checks:
        if check.status in ("passed", "failed", "error") and check.command:
            lines.append(f"### {check.id} — {check.command}")
            lines.append("")
            if check.reason:
                lines.append(f"Reason: {check.reason}")
                lines.append("")
            evidence = check.evidence_lines()
            if evidence:
                lines.append("```")
                lines.extend(evidence)
                lines.append("```")
            lines.append("")
    if report.findings:
        lines.append("## Findings")
        lines.append("")
        for index, finding in enumerate(report.findings, start=1):
            lines.append(
                f"### F-{index:03d} [{finding.severity}] {finding.title}"
            )
            lines.append("")
            if finding.description:
                lines.append(finding.description)
                lines.append("")
            for evidence_text in finding.evidence:
                lines.append(f"```\n{evidence_text}\n```")
            lines.append("")
    skipped_rows: list[tuple] = []
    seen_skipped: set = set()
    for entry in report.skipped_checks:
        identifier = entry.get("id", "")
        if identifier and identifier not in seen_skipped:
            seen_skipped.add(identifier)
            skipped_rows.append((identifier, entry.get("reason", "")))
    for check in report.checks:
        if check.status in ("skipped", "unverified") and check.id not in seen_skipped:
            seen_skipped.add(check.id)
            skipped_rows.append((check.id, check.reason or ""))
    if skipped_rows:
        lines.append("## Skipped checks")
        lines.append("")
        for identifier, reason in skipped_rows:
            lines.append(f"- `{identifier}`: {reason}")
        lines.append("")
    if report.execution_errors:
        lines.append("## Execution errors")
        lines.append("")
        for error in report.execution_errors:
            lines.append(f"- `{error.check_id}`: {error.message}")
        lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for limitation in report.limitations:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def render_text(report: Report) -> str:
    """One-line-per-check console summary."""
    lines: list[str] = []
    lines.append(f"PatchProof {report.patchproof_version} — overall: {report.overall_status}")
    lines.append(
        f"repository: {report.repository.get('path', '?')} "
        f"(revision {report.repository.get('revision') or 'unknown'}, "
        f"selection {report.selection_policy})"
    )
    if report.changed_files:
        lines.append(f"examined files: {len(report.changed_files)}")
    for check in report.checks:
        exit_code = check.exit_code if check.exit_code is not None else "-"
        duration = f"{check.duration_s:g}s" if check.duration_s is not None else "-"
        required = "required" if check.required else "optional"
        lines.append(
            f"  [{_STATUS_MARK.get(check.status, check.status)}] {check.id} "
            f"({required}) exit={exit_code} {duration} — {check.tool}"
        )
        if check.reason:
            lines.append(f"      reason: {check.reason}")
    if report.findings:
        lines.append(f"findings: {len(report.findings)} (see report for details)")
    return "\n".join(lines)
