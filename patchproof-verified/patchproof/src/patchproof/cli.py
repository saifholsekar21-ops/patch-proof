"""PatchProof command-line interface.

Exit codes (stable, documented in README):

- ``verify``:  0 = overall passed, 1 = failed, 2 = error, 3 = unverified,
  4 = usage/input/config error.
- ``inspect``: 0 = success, 4 = input error.
- ``report``:  0 = success, 4 = input error (unreadable or invalid report).
- ``config validate``: 0 = valid, 1 = invalid, 4 = input error.
- Usage errors (unknown options, missing arguments): 4.

Run ``patchproof --help`` for the full command reference.
"""

from __future__ import annotations

import os
import sys

import typer

from . import __version__
from .config import ConfigError, load_config
from .detect import detect_project
from .engine import VerificationError, run_verification
from .models import Report
from .render import render_json, render_markdown, render_text
from .repo import ChangeSet, GitError, changed_files, repo_info
from .secrets import redact_text
from .validate import ReportLoadError, load_report, validate_report

app = typer.Typer(
    name="patchproof",
    help="Evidence-based code verification: inspect repositories, run checks, "
    "and produce verifiable reports.",
    no_args_is_help=True,
    add_completion=False,
)

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_ERROR = 2
EXIT_UNVERIFIED = 3
EXIT_USAGE = 4

_OVERALL_EXIT = {
    "passed": EXIT_PASSED,
    "failed": EXIT_FAILED,
    "error": EXIT_ERROR,
    "unverified": EXIT_UNVERIFIED,
}


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"patchproof {__version__}")
        raise typer.Exit()


@app.callback()
def _callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the patchproof version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """PatchProof: evidence-based code verification."""


def _resolve_root(path: str) -> str:
    normalized = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(normalized):
        raise typer.BadParameter(f"path is not a directory: {path!r}")
    return normalized


def _load_config_or_exit(path: str | None):
    try:
        return load_config(path)
    except ConfigError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from None


@app.command()
def inspect(path: str = typer.Argument(".", help="Repository path.")) -> None:
    """Show repository identity, git state, and detected tooling."""
    root = _resolve_root(path)
    info = repo_info(root)
    facts = detect_project(root)
    typer.echo(f"repository : {root}")
    typer.echo(f"git        : {'repository' if info.is_repository else 'not a git repository'}")
    if info.is_repository:
        typer.echo(
            f"             branch={info.branch or '(detached)'} "
            f"revision={info.head_revision or 'unknown'} dirty={info.dirty}"
        )
    typer.echo(f"languages  : {', '.join(facts.languages) or '(none detected)'}")
    if facts.frameworks:
        typer.echo(f"frameworks : {', '.join(sorted(set(facts.frameworks)))}")
    for hint in facts.hints:
        state = "available" if hint.available else "missing"
        version = f" ({hint.version})" if hint.version else ""
        typer.echo(
            f"tooling    : {hint.purpose:<9} {' '.join(hint.command)} "
            f"[{state}{version}] ({hint.basis})"
        )
    for warning in facts.warnings:
        typer.echo(f"warning    : {warning}")
    raise typer.Exit(EXIT_PASSED)


@app.command()
def verify(
    path: str = typer.Argument(".", help="Repository path."),
    select: str | None = typer.Option(
        None,
        "--select",
        help="Change selection: working, staged, unstaged, untracked, "
        "committed, all, none. Overrides the config value.",
    ),
    base: str | None = typer.Option(
        None, "--base", help="Base revision for committed change selection."
    ),
    head: str | None = typer.Option(
        None, "--head", help="Head revision for committed change selection."
    ),
    config_path: str | None = typer.Option(
        None, "--config", help="Path to a patchproof TOML configuration file."
    ),
    fmt: str | None = typer.Option(
        None, "--format", help="Report format: json, markdown, text (default: config value)."
    ),
    output: str | None = typer.Option(
        None, "--output", help="Write the report to this file instead of stdout."
    ),
    task_id: str = typer.Option(
        "patchproof-run", "--task-id", help="Task identifier for the report."
    ),
    task_description: str = typer.Option(
        "", "--task-description", help="One-line task description for the report."
    ),
) -> None:
    """Run verification checks and produce an evidence-backed report."""
    config = _load_config_or_exit(config_path)
    report_format = fmt or config.report.format
    if report_format not in ("json", "markdown", "text"):
        raise typer.BadParameter("--format must be one of: json, markdown, text")
    root = _resolve_root(path)

    selection = select or config.git.selection
    base_rev = base or config.git.base
    head_rev = head or config.git.head

    info = repo_info(root)
    if not info.is_repository:
        if selection != "none":
            typer.echo(
                f"ERROR: {root!r} is not a git repository. Use --select none to "
                "verify without change analysis.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE) from None
        change_set = ChangeSet(
            selection="none",
            notes=[f"{root!r} is not a git repository; no change analysis performed"],
        )
    else:
        try:
            change_set = changed_files(root, selection=selection, base=base_rev, head=head_rev)
        except GitError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(EXIT_USAGE) from None

    task = task_description or f"patchproof verify in {root}"
    try:
        report = run_verification(root, config, change_set, task_id=task_id, task_description=task)
    except VerificationError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None

    payload = _render(report, report_format, config.report.redact)
    destination = output or config.report.destination or None
    _emit(payload, destination, report_format)
    typer.echo(render_text(report), err=True)
    raise typer.Exit(_OVERALL_EXIT[report.overall_status])


def _render(report: Report, fmt: str, redact: bool) -> str:
    if fmt == "json":
        return render_json(report, redact=redact)
    if fmt == "markdown":
        return render_markdown(report)
    return render_text(report)


def _emit(payload: str, output: str | None, fmt: str) -> None:
    if output:
        try:
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except OSError as exc:
            typer.echo(f"ERROR: cannot write report to {output!r}: {exc}", err=True)
            raise typer.Exit(EXIT_USAGE) from None
        typer.echo(f"report written to {output}")
    else:
        typer.echo(payload, nl=False)


@app.command()
def report(
    file: str = typer.Argument(..., help="Path to a saved report JSON file."),
    fmt: str = typer.Option("text", "--format", help="Output format: json, markdown, text."),
    output: str | None = typer.Option(
        None, "--output", help="Write the rendered report to this file instead of stdout."
    ),
) -> None:
    """Load, validate, and render a saved verification report."""
    # Some Typer/Click combinations call the callback with None instead of
    # raising MissingParameter for an omitted required argument.
    if not file:
        raise typer.BadParameter("missing argument: FILE")
    if fmt not in ("json", "markdown", "text"):
        raise typer.BadParameter("--format must be one of: json, markdown, text")
    try:
        data = load_report(file)
    except ReportLoadError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from None
    result = validate_report(data)
    if not result["valid"]:
        typer.echo(f"ERROR: report {file!r} is invalid:", err=True)
        for entry in result["errors"]:
            typer.echo(
                f"  [{entry.get('code', 'schema')}] {entry['path']}: {entry['message']}",
                err=True,
            )
        raise typer.Exit(EXIT_USAGE) from None
    try:
        coerced = _coerce_report(data)
        coerced["checks"] = [
            _coerce_check(entry) for entry in data.get("checks", [])
        ]
        model = Report.model_validate(coerced)
    except Exception as exc:
        typer.echo(f"ERROR: cannot render report: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from None
    payload = _render(model, fmt, redact=False)
    _emit(payload, output, fmt)
    raise typer.Exit(EXIT_PASSED)


_LEGACY_STATUS_MAP = {
    "PASS": "passed",
    "FAIL": "failed",
    "SKIPPED": "skipped",
    "NOT_RUN": "unverified",
    "ERROR": "error",
}


def _coerce_check(entry: dict) -> dict:
    """Map a schema check entry back onto the CheckResult model."""
    evidence = entry.get("evidence") or []
    stderr = "\n".join(evidence)
    if entry.get("summary"):
        stderr = f"{entry['summary']}\n{stderr}" if stderr else entry["summary"]
    status = entry.get("status")
    if isinstance(status, str) and status in _LEGACY_STATUS_MAP:
        status = _LEGACY_STATUS_MAP[status]
    return {
        "id": entry["id"],
        "category": entry.get("category", "custom"),
        "tool": entry["tool"],
        "command": entry.get("command", ""),
        "status": status,
        "required": bool(entry.get("required", True)),
        "exit_code": entry.get("exit_code"),
        "duration_s": entry.get("duration_s"),
        "reason": entry.get("reason"),
        "stderr": stderr,
    }


def _coerce_report(data: dict) -> dict:
    """Normalize a validated 1.0 report document onto the 1.1 model.

    Schema 1.0 reports have no overall_status, patchproof_version, or
    changed_files (they carry ``changes``). The overall status is derived
    from the checks under the 1.1 policy so the rendered view is consistent;
    the original document is left untouched.
    """
    if data.get("schema_version") != "1.0":
        return data
    changed_files = [
        {"path": change["file"], "origin": "schema 1.0 change entry"}
        for change in data.get("changes") or []
        if isinstance(change, dict) and isinstance(change.get("file"), str)
    ]
    findings = [
        {
            "severity": finding.get("severity", "info"),
            "title": finding.get("title", ""),
            "description": finding.get("description", ""),
            "evidence": finding.get("evidence") or [],
            "locations": finding.get("locations") or [],
        }
        for finding in data.get("findings") or []
        if isinstance(finding, dict)
    ]
    checks = [
        _coerce_check(entry)
        for entry in data.get("checks", [])
        if isinstance(entry, dict)
    ]
    return {
        "schema_version": "1.1",
        "patchproof_version": data.get("patchproof_version") or "unknown",
        "task_id": data.get("task_id", ""),
        "task_description": data.get("task_description", ""),
        "generated_at": data.get("generated_at"),
        "repository": data.get("repository") or {},
        "selection_policy": data.get("selection_policy") or "legacy-1.0",
        "changed_files": changed_files,
        "checks": checks,
        "findings": findings,
        "skipped_checks": data.get("skipped_checks") or [],
        "execution_errors": data.get("execution_errors") or [],
        "overall_status": data.get("overall_status") or _derive_overall(checks),
        "limitations": data.get("limitations") or [],
        "conclusion": data.get("conclusion", ""),
    }


def _derive_overall(checks: list[dict]) -> str:
    """Apply the 1.1 overall-status policy to coerced check entries."""
    required = [check for check in checks if check.get("required", True)]
    if any(check["status"] == "failed" for check in required):
        return "failed"
    if any(check["status"] == "error" for check in required):
        return "error"
    if not required or any(
        check["status"] in ("unverified", "skipped") for check in required
    ):
        return "unverified"
    return "passed"


config_app = typer.Typer(
    name="config",
    help="Configuration utilities.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(config_app)


@config_app.command()
def validate(
    path: str | None = typer.Option(
        None, "--config", help="Path to a patchproof TOML configuration file."
    ),
) -> None:
    """Validate a patchproof configuration file (defaults are used without --config)."""
    try:
        loaded = load_config(path)
    except ConfigError as exc:
        typer.echo(f"INVALID: {exc}")
        raise typer.Exit(1) from None
    source = path if path else "(built-in defaults)"
    typer.echo(f"VALID: {source}")
    typer.echo(f"  required categories: {', '.join(loaded.checks.required)}")
    typer.echo(f"  optional categories: {', '.join(loaded.checks.optional)}")
    typer.echo(
        f"  timeout: {loaded.limits.timeout_s:g}s, "
        f"output limit: {loaded.limits.output_limit_bytes} bytes"
    )
    typer.echo(f"  git selection: {loaded.git.selection}")
    typer.echo(f"  report format: {loaded.report.format}, redact: {loaded.report.redact}")
    for category in ("tests", "lint", "typecheck", "deps"):
        override = getattr(loaded.checks, category).command
        if override:
            typer.echo(f"  {category} override: {redact_text(' '.join(override))}")
    for custom in loaded.checks.custom:
        typer.echo(
            f"  custom {custom.name} (required={custom.required}): "
            f"{redact_text(' '.join(custom.command))}"
        )
    raise typer.Exit(0)


def _usage_error_types() -> tuple[type[BaseException], ...]:
    """Public exception classes that signal a command-line usage mistake.

    Typer's public surface differs between release lines. Upstream Typer
    raises Click's ``UsageError`` subclasses and does not re-export all of
    them; some Typer releases bundle Click and expose the shared base as
    ``typer.TyperException``. Collect whichever public classes exist instead
    of importing a private module or assuming one specific layout.
    """
    candidates: list[type[BaseException] | None] = []
    try:
        import click
    except ImportError:
        pass
    else:
        candidates.append(getattr(click, "UsageError", None))
    candidates.extend(
        getattr(typer, name, None)
        for name in ("UsageError", "BadParameter", "TyperException")
    )
    types: list[type[BaseException]] = []
    for candidate in candidates:
        if (
            isinstance(candidate, type)
            and issubclass(candidate, Exception)
            and candidate not in types
        ):
            types.append(candidate)
    return tuple(types)


_USAGE_ERRORS = _usage_error_types()


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point. Usage errors map to exit code 4.

    ``typer.Exit`` is handled first because it carries an explicit exit code.
    Usage errors (unknown options, missing commands or arguments, invalid
    parameter values) are reported without a traceback; unexpected programming
    errors are deliberately left to propagate.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = app(args, standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code or 0)
    except _USAGE_ERRORS as exc:
        message = exc.format_message() if hasattr(exc, "format_message") else str(exc)
        typer.echo(f"ERROR: {message}", err=True)
        return EXIT_USAGE
    if result is not None:
        return int(result)
    return EXIT_PASSED


if __name__ == "__main__":
    sys.exit(main())
