"""PatchProof report schema validation.

Validates machine-readable verification reports against schema 1.0 (the
original PatchProof contract, uppercase statuses) and 1.1 (lowercase
statuses plus optional fields: patchproof_version, overall_status,
selection_policy, execution_errors).

Read-only: never modifies the input report unless a caller explicitly uses
the redaction helpers from patchproof.secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .secrets import find_secrets_in_string, redact_report

SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1")
LATEST_SCHEMA_VERSION = "1.1"
# Backward-compatible alias kept for the standalone scripts/validate_report.py
SCHEMA_VERSION = LATEST_SCHEMA_VERSION

# Schema 1.0 status vocabulary (original contract)
CHECK_STATUSES_V10 = ("PASS", "FAIL", "SKIPPED", "ERROR", "NOT_RUN")
# Schema 1.1 status vocabulary (CLI vocabulary)
CHECK_STATUSES_V11 = ("passed", "failed", "skipped", "error", "unverified")

FINDING_SEVERITIES = ("critical", "high", "medium", "low", "info")
FINDING_STATUSES = ("open", "fixed", "wontfix", "duplicate")
VERIFICATION_STATUSES = ("verified", "unverified", "proposed")
OVERALL_STATUSES = ("passed", "failed", "error", "unverified")

MAX_REPORT_BYTES = 10 * 1024 * 1024
MAX_NESTING_DEPTH = 64


class ReportLoadError(Exception):
    """Raised when the report file cannot be read or parsed."""


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def load_report(path: str) -> dict[str, Any]:
    """Read and parse the report file at *path*.

    Raises ReportLoadError with a clean message for missing files, unreadable
    files, oversized files, non-JSON input, and pathological nesting.
    """
    report_path = Path(path)
    try:
        size = report_path.stat().st_size
    except OSError as exc:
        raise ReportLoadError(f"cannot read file {path!r}: {exc}") from exc
    if size > MAX_REPORT_BYTES:
        raise ReportLoadError(
            f"report too large: {size} bytes (limit {MAX_REPORT_BYTES})"
        )
    try:
        raw = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportLoadError(f"cannot read file {path!r}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ReportLoadError(f"file {path!r} is not valid UTF-8: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReportLoadError(
            f"malformed JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except RecursionError as exc:
        raise ReportLoadError(
            f"malformed JSON: nesting exceeds {MAX_NESTING_DEPTH} levels"
        ) from exc
    if not isinstance(data, dict):
        raise ReportLoadError(
            "report root must be a JSON object, got " + type(data).__name__
        )
    return data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class _Validator:
    def __init__(self, schema_version: str) -> None:
        self.schema_version = schema_version
        self.errors: list[dict[str, str]] = []
        self.warnings: list[dict[str, str]] = []
        self.secrets: list[dict[str, str]] = []
        self._seen_ids: dict[str, str] = {}
        self._check_status_by_id: dict[str, str] = {}

    @property
    def _statuses(self) -> Sequence[str]:
        return CHECK_STATUSES_V10 if self.schema_version == "1.0" else CHECK_STATUSES_V11

    @property
    def _pass_status(self) -> str:
        return "PASS" if self.schema_version == "1.0" else "passed"

    def error(self, path: str, message: str, code: str = "schema") -> None:
        self.errors.append({"path": path, "code": code, "message": message})

    def warning(self, path: str, message: str) -> None:
        self.warnings.append({"path": path, "message": message})

    # -- scalar helpers -----------------------------------------------------

    def _require_str(
        self, node: dict[str, Any], key: str, path: str, *, allow_empty: bool = False
    ) -> str | None:
        value = node.get(key)
        if not isinstance(value, str):
            self.error(path, f"'{key}' must be a string")
            return None
        if not allow_empty and not value.strip():
            self.error(path, f"'{key}' must not be empty")
            return None
        return value

    def _optional_str(self, node: dict[str, Any], key: str, path: str) -> None:
        value = node.get(key)
        if value is not None and not isinstance(value, str):
            self.error(path, f"'{key}' must be a string or null")

    def _optional_number(
        self, node: dict[str, Any], key: str, path: str, *, minimum: float | None = None
    ) -> None:
        value = node.get(key)
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.error(path, f"'{key}' must be a number or null")
            return
        if minimum is not None and value < minimum:
            self.error(path, f"'{key}' must be >= {minimum}")

    def _require_string_list(
        self, node: dict[str, Any], key: str, path: str, *, allow_empty: bool = False
    ) -> list[str]:
        value = node.get(key)
        if not isinstance(value, list):
            self.error(path, f"'{key}' must be an array of strings")
            return []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                self.error(f"{path}.{key}[{index}]", "must be a string")
        if not allow_empty and len(value) == 0:
            self.error(path, f"'{key}' must not be empty")
        return [item for item in value if isinstance(item, str)]

    def _check_unique_id(self, identifier: str, path: str, kind: str) -> None:
        previous = self._seen_ids.get(identifier)
        if previous is not None:
            self.error(
                path,
                f"duplicate id {identifier!r}: already used at {previous}",
                code="duplicate_id",
            )
        else:
            self._seen_ids[identifier] = path

    # -- secret scan --------------------------------------------------------

    def _scan_value(self, value: Any, path: str) -> None:
        if isinstance(value, str):
            self.secrets.extend(find_secrets_in_string(value, path))
        elif isinstance(value, dict):
            for key, item in value.items():
                self._scan_value(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._scan_value(item, f"{path}[{index}]")

    # -- sections -----------------------------------------------------------

    def validate(self, report: dict[str, Any]) -> None:
        self._validate_root(report)
        self._validate_repository(report.get("repository"), "repository")
        self._validate_findings(report.get("findings"), "findings")
        self._validate_checks(report.get("checks"), "checks")
        self._validate_changes(report.get("changes"), "changes")
        self._validate_skipped_checks(report.get("skipped_checks"), "skipped_checks")
        self._validate_execution_errors(report.get("execution_errors"), "execution_errors")
        self._validate_changed_files(report.get("changed_files"), "changed_files")
        self._validate_string_list(report.get("limitations"), "limitations", required=False)
        self._optional_str(report, "conclusion", "conclusion")
        self._scan_value(report, "$")
        for secret in self.secrets:
            self.error(
                secret["path"],
                f"secret material detected ({secret['kind']}); reports must "
                "never contain raw credentials",
                code="secret_material",
            )

    def _validate_root(self, report: dict[str, Any]) -> None:
        allowed = {
            "schema_version",
            "task_id",
            "task_description",
            "generated_at",
            "repository",
            "findings",
            "checks",
            "changes",
            "skipped_checks",
            "limitations",
            "conclusion",
            # schema 1.1 additions
            "patchproof_version",
            "overall_status",
            "selection_policy",
            "execution_errors",
            "changed_files",
        }
        for key in report:
            if key not in allowed:
                self.warning(f"$.{key}", "unknown top-level field (ignored)")
        version = report.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            self.error(
                "schema_version",
                f"unsupported schema version {version!r}; expected one of "
                + ", ".join(SUPPORTED_SCHEMA_VERSIONS),
                code="schema_version",
            )
        self._require_str(report, "task_id", "task_id")
        self._require_str(report, "task_description", "task_description")
        self._require_str(report, "generated_at", "generated_at")
        # 1.1 additions
        self._optional_str(report, "patchproof_version", "patchproof_version")
        self._optional_str(report, "selection_policy", "selection_policy")
        overall = report.get("overall_status")
        if overall is not None and overall not in OVERALL_STATUSES:
            self.error(
                "overall_status",
                f"unsupported overall status {overall!r}; expected one of "
                + ", ".join(OVERALL_STATUSES),
                code="enum",
            )

    def _validate_repository(self, node: Any, path: str) -> None:
        if node is None:
            self.error(path, "required section 'repository' is missing")
            return
        if not isinstance(node, dict):
            self.error(path, "must be an object")
            return
        self._require_str(node, "path", f"{path}.path")
        self._optional_str(node, "revision", f"{path}.revision")
        self._optional_str(node, "branch", f"{path}.branch")
        if "dirty" in node and node["dirty"] is not None and not isinstance(
            node["dirty"], bool
        ):
            self.error(f"{path}.dirty", "must be a boolean or null")

    def _validate_findings(self, node: Any, path: str) -> None:
        if node is None:
            self.error(path, "required section 'findings' is missing (use [] when none)")
            return
        if not isinstance(node, list):
            self.error(path, "must be an array")
            return
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                self.error(item_path, "must be an object")
                continue
            identifier = self._require_str(item, "id", f"{item_path}.id")
            if identifier:
                self._check_unique_id(identifier, f"{item_path}.id", "finding")
            severity = item.get("severity")
            if severity not in FINDING_SEVERITIES:
                self.error(
                    f"{item_path}.severity",
                    f"unsupported severity {severity!r}; expected one of "
                    + ", ".join(FINDING_SEVERITIES),
                    code="enum",
                )
            status = item.get("status", "open")
            if status not in FINDING_STATUSES:
                self.error(
                    f"{item_path}.status",
                    f"unsupported finding status {status!r}; expected one of "
                    + ", ".join(FINDING_STATUSES),
                    code="enum",
                )
            self._require_str(item, "title", f"{item_path}.title")
            self._require_str(item, "description", f"{item_path}.description")
            self._require_string_list(item, "evidence", f"{item_path}.evidence")
            locations = item.get("locations")
            if locations is not None:
                if not isinstance(locations, list):
                    self.error(f"{item_path}.locations", "must be an array")
                else:
                    for loc_index, loc in enumerate(locations):
                        loc_path = f"{item_path}.locations[{loc_index}]"
                        if not isinstance(loc, dict):
                            self.error(loc_path, "must be an object")
                            continue
                        file_name = loc.get("file")
                        if not isinstance(file_name, str) or not file_name:
                            self.error(f"{loc_path}.file", "must be a non-empty string")
                        else:
                            self._warn_traversal(file_name, f"{loc_path}.file")
                        if "line" in loc and (
                            isinstance(loc["line"], bool)
                            or not isinstance(loc["line"], int)
                            or loc["line"] < 1
                        ):
                            self.error(f"{loc_path}.line", "must be a positive integer")

    def _warn_traversal(self, file_name: str, path: str) -> None:
        parts = Path(file_name.replace("\\", "/")).parts
        if ".." in parts:
            self.warning(path, f"path contains '..' traversal: {file_name!r}")

    def _validate_checks(self, node: Any, path: str) -> None:
        if node is None:
            self.error(path, "required section 'checks' is missing (use [] when none)")
            return
        if not isinstance(node, list):
            self.error(path, "must be an array")
            return
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                self.error(item_path, "must be an object")
                continue
            identifier = self._require_str(item, "id", f"{item_path}.id")
            if identifier:
                self._check_unique_id(identifier, f"{item_path}.id", "check")
            status = item.get("status")
            if status not in self._statuses:
                self.error(
                    f"{item_path}.status",
                    f"unsupported check status {status!r} for schema "
                    f"{self.schema_version}; expected one of "
                    + ", ".join(self._statuses),
                    code="enum",
                )
                continue
            if identifier:
                self._check_status_by_id[identifier] = str(status)
            self._require_str(item, "tool", f"{item_path}.tool")
            self._require_str(item, "command", f"{item_path}.command")
            self._optional_str(item, "summary", f"{item_path}.summary")
            self._optional_str(item, "reason", f"{item_path}.reason")
            self._optional_str(item, "category", f"{item_path}.category")
            exit_code = item.get("exit_code")
            if exit_code is not None and (
                isinstance(exit_code, bool) or not isinstance(exit_code, int)
            ):
                self.error(f"{item_path}.exit_code", "must be an integer or null")
            self._optional_number(item, "duration_s", f"{item_path}.duration_s", minimum=0)
            required = item.get("required")
            if required is not None and not isinstance(required, bool):
                self.error(f"{item_path}.required", "must be a boolean or omitted")
            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                self.error(f"{item_path}.evidence", "must be an array of strings")
                evidence = []
            else:
                for ev_index, entry in enumerate(evidence):
                    if not isinstance(entry, str):
                        self.error(f"{item_path}.evidence[{ev_index}]", "must be a string")
            has_exit_code = exit_code is not None
            has_evidence = any(isinstance(e, str) and e.strip() for e in evidence)
            reason = item.get("reason")
            running_statuses = ("PASS", "FAIL", "ERROR") if self.schema_version == "1.0" else (
                "passed",
                "failed",
                "error",
            )
            if status in running_statuses:
                if not has_exit_code and not has_evidence:
                    self.error(
                        f"{item_path}.evidence",
                        f"check with status {status} must provide an exit_code or "
                        "non-empty evidence",
                        code="missing_evidence",
                    )
            else:  # SKIPPED / NOT_RUN or skipped / unverified
                if not isinstance(reason, str) or not reason.strip():
                    self.error(
                        f"{item_path}.reason",
                        f"check with status {status} must provide a non-empty reason",
                        code="missing_reason",
                    )

    def _validate_changes(self, node: Any, path: str) -> None:
        if node is None:
            self.error(path, "required section 'changes' is missing (use [] when none)")
            return
        if not isinstance(node, list):
            self.error(path, "must be an array")
            return
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                self.error(item_path, "must be an object")
                continue
            identifier = self._require_str(item, "id", f"{item_path}.id")
            if identifier:
                self._check_unique_id(identifier, f"{item_path}.id", "change")
            self._require_str(item, "file", f"{item_path}.file")
            self._require_str(item, "description", f"{item_path}.description")
            status = item.get("verification_status")
            if status not in VERIFICATION_STATUSES:
                self.error(
                    f"{item_path}.verification_status",
                    f"unsupported verification status {status!r}; expected one of "
                    + ", ".join(VERIFICATION_STATUSES),
                    code="enum",
                )
                continue
            verified_by = item.get("verified_by", [])
            if not isinstance(verified_by, list) or any(
                not isinstance(entry, str) for entry in verified_by
            ):
                self.error(f"{item_path}.verified_by", "must be an array of check ids")
                continue
            if status == "verified":
                if not verified_by:
                    self.error(
                        f"{item_path}.verified_by",
                        "a 'verified' change must list at least one check in "
                        "'verified_by'",
                        code="unverified_claim",
                    )
                for check_id in verified_by:
                    check_status = self._check_status_by_id.get(check_id)
                    if check_status is None:
                        self.error(
                            f"{item_path}.verified_by",
                            f"verified_by references unknown check {check_id!r}",
                            code="unverified_claim",
                        )
                    elif check_status != self._pass_status:
                        self.error(
                            f"{item_path}.verified_by",
                            f"check {check_id!r} has status {check_status}, "
                            "so it cannot verify a change",
                            code="unverified_claim",
                        )
            elif verified_by:
                self.error(
                    f"{item_path}.verified_by",
                    f"'{status}' change must not list checks in 'verified_by'",
                    code="unverified_claim",
                )

    def _validate_skipped_checks(self, node: Any, path: str) -> None:
        if node is None:
            return
        if not isinstance(node, list):
            self.error(path, "must be an array")
            return
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                self.error(item_path, "must be an object")
                continue
            identifier = self._require_str(item, "id", f"{item_path}.id")
            if identifier:
                self._check_unique_id(identifier, f"{item_path}.id", "skipped_check")
            self._require_str(item, "tool", f"{item_path}.tool")
            self._require_str(item, "reason", f"{item_path}.reason")

    def _validate_execution_errors(self, node: Any, path: str) -> None:
        if node is None:
            return
        if not isinstance(node, list):
            self.error(path, "must be an array")
            return
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                self.error(item_path, "must be an object")
                continue
            self._require_str(item, "check_id", f"{item_path}.check_id")
            self._require_str(item, "message", f"{item_path}.message")

    def _validate_changed_files(self, node: Any, path: str) -> None:
        """Schema 1.1: examined files and their diff metadata."""
        if node is None:
            return
        if not isinstance(node, list):
            self.error(path, "must be an array")
            return
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                self.error(item_path, "must be an object")
                continue
            self._require_str(item, "path", f"{item_path}.path")
            self._optional_str(item, "status", f"{item_path}.status")
            self._optional_str(item, "old_path", f"{item_path}.old_path")
            self._optional_str(item, "origin", f"{item_path}.origin")
            for field in ("additions", "deletions"):
                value = item.get(field)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                ):
                    self.error(f"{item_path}.{field}", "must be a non-negative integer or null")

    def _validate_string_list(self, node: Any, path: str, *, required: bool = True) -> None:
        if node is None:
            if required:
                self.error(path, f"required section '{path}' is missing")
            return
        if not isinstance(node, list):
            self.error(path, "must be an array of strings")
            return
        for index, item in enumerate(node):
            if not isinstance(item, str):
                self.error(f"{path}[{index}]", "must be a string")


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate an already-parsed report dict.

    Returns {"valid": bool, "schema_version": str, "errors": [...],
    "warnings": [...], "secrets": [...]}.
    """
    version = report.get("schema_version") if isinstance(report, dict) else None
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        version = LATEST_SCHEMA_VERSION
    validator = _Validator(version)
    validator.validate(report)
    return {
        "valid": len(validator.errors) == 0,
        "schema_version": version,
        "errors": validator.errors,
        "warnings": validator.warnings,
        "secrets": validator.secrets,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a PatchProof verification report against the "
        f"report contract (schemas {', '.join(SUPPORTED_SCHEMA_VERSIONS)})."
    )
    parser.add_argument("report", help="path to the report JSON file")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument(
        "--redact-output",
        metavar="FILE",
        help="write a copy of the report with detected secrets redacted to FILE",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        data = load_report(args.report)
    except ReportLoadError as exc:
        error_result = {"valid": False, "error": str(exc)}
        if args.json:
            print(json.dumps(error_result, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.redact_output:
        try:
            redacted = redact_report(data)
            Path(args.redact_output).write_text(
                json.dumps(redacted, indent=2) + "\n", encoding="utf-8"
            )
            data = redacted
        except OSError as exc:
            error_result = {
                "valid": False,
                "error": f"cannot write redacted output to {args.redact_output!r}: {exc}",
            }
            if args.json:
                print(json.dumps(error_result, indent=2))
            else:
                print(error_result["error"], file=sys.stderr)
            return 2

    result: dict[str, Any] = validate_report(data)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 1

    if result["errors"]:
        print(f"INVALID ({len(result['errors'])} error(s))")
        for entry in result["errors"]:
            print(f"  [{entry.get('code', 'schema')}] {entry['path']}: {entry['message']}")
    else:
        print("VALID")
    for entry in result["warnings"]:
        print(f"  WARNING {entry['path']}: {entry['message']}")
    if result["secrets"]:
        print(
            f"  SECRET {result['secrets'][0]['path']}: {result['secrets'][0]['kind']} "
            f"(+{len(result['secrets']) - 1} more)"
        )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
