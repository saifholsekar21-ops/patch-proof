"""Check execution primitives: controlled subprocesses with bounded output."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from ..models import CheckResult, CheckStatus
from ..secrets import redact_text


@dataclass
class CheckSpec:
    """A single check to execute. *command* is an argument array."""

    id: str
    category: str
    tool: str
    command: list[str]
    required: bool
    timeout_s: float
    cwd: str

    @property
    def display_command(self) -> str:
        return " ".join(self.command)


def missing_tool_result(spec: CheckSpec) -> CheckResult | None:
    """Return a result when the check's executable is not on PATH.

    A missing executable is an error for required checks and a skip for
    optional ones — never a pass, and never silently dropped.
    """
    executable = spec.command[0]
    if shutil.which(executable) is not None:
        return None
    status: CheckStatus = "error" if spec.required else "skipped"
    return CheckResult(
        id=spec.id,
        category=spec.category,
        tool=spec.tool,
        command=spec.display_command,
        status=status,
        required=spec.required,
        reason=f"executable {executable!r} not found on PATH",
    )


def run_check(spec: CheckSpec, output_limit_bytes: int) -> CheckResult:
    """Execute *spec* with a timeout and bounded, redacted output capture.

    Output is drained to temporary files (never pipes held in memory), so an
    unboundedly chatty check cannot exhaust memory; at most
    *output_limit_bytes* per stream are retained. Captured output is redacted
    before it is stored. Returns a CheckResult in every case — this function
    does not raise for process-level failures.
    """
    missing = missing_tool_result(spec)
    if missing is not None:
        return missing

    started = time.monotonic()
    stdout_handle = tempfile.TemporaryFile(mode="w+b")
    stderr_handle = tempfile.TemporaryFile(mode="w+b")
    try:
        process = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
        try:
            process.communicate(timeout=spec.timeout_s)
        except subprocess.TimeoutExpired:
            _terminate(process)
            return CheckResult(
                id=spec.id,
                category=spec.category,
                tool=spec.tool,
                command=spec.display_command,
                status="error",
                required=spec.required,
                duration_s=round(spec.timeout_s, 3),
                reason=f"timed out after {spec.timeout_s:g}s",
            )
        duration = round(time.monotonic() - started, 3)
        stdout = _read_bounded(stdout_handle, output_limit_bytes)
        stderr = _read_bounded(stderr_handle, output_limit_bytes)
        status: CheckStatus = "passed" if process.returncode == 0 else "failed"
        return CheckResult(
            id=spec.id,
            category=spec.category,
            tool=spec.tool,
            command=spec.display_command,
            status=status,
            required=spec.required,
            duration_s=duration,
            exit_code=process.returncode,
            stdout=redact_text(stdout),
            stderr=redact_text(stderr),
        )
    except OSError as exc:
        return CheckResult(
            id=spec.id,
            category=spec.category,
            tool=spec.tool,
            command=spec.display_command,
            status="error",
            required=spec.required,
            duration_s=round(time.monotonic() - started, 3),
            reason=f"failed to start {spec.command[0]!r}: {exc}",
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()


def _terminate(process: subprocess.Popen) -> None:
    """Terminate a timed-out process, then kill it if it ignores the signal."""
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    except OSError:
        pass


def _read_bounded(handle, limit: int) -> str:
    """Read up to *limit* bytes from the start of *handle*."""
    handle.seek(0)
    data = handle.read(limit + 1)
    if len(data) > limit:
        return data[:limit].decode("utf-8", errors="replace") + (
            f"\n...[output truncated at {limit} bytes]"
        )
    return data.decode("utf-8", errors="replace")


__all__ = ["CheckSpec", "run_check", "missing_tool_result"]
