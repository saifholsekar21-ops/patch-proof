"""Tests for check execution primitives: timeouts, truncation, isolation."""

from __future__ import annotations

import sys

from patchproof.checks.base import CheckSpec, run_check

PY = sys.executable


def spec(
    command: list[str],
    *,
    required: bool = True,
    timeout_s: float = 30.0,
    cwd: str = ".",
) -> CheckSpec:
    return CheckSpec(
        id="t",
        category="tests",
        tool=command[0] if command else "none",
        command=command,
        required=required,
        timeout_s=timeout_s,
        cwd=cwd,
    )


def test_passing_check_reports_exit_zero_and_output():
    result = run_check(spec([PY, "-c", "print('hello')"]), 4096)
    assert result.status == "passed"
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.duration_s is not None and result.duration_s >= 0


def test_failing_check_is_failed_not_error():
    result = run_check(spec([PY, "-c", "import sys; sys.exit(3)"]), 4096)
    assert result.status == "failed"
    assert result.exit_code == 3


def test_missing_required_executable_is_error():
    result = run_check(spec(["definitely-not-a-real-tool-xyz"]), 4096)
    assert result.status == "error"
    assert result.reason is not None and "not found" in result.reason
    assert result.exit_code is None


def test_missing_optional_executable_is_skipped():
    result = run_check(spec(["definitely-not-a-real-tool-xyz"], required=False), 4096)
    assert result.status == "skipped"
    assert result.reason is not None and "not found" in result.reason


def test_timeout_terminates_and_reports_error():
    slow = spec([PY, "-c", "import time; time.sleep(60)"], timeout_s=1.0)
    result = run_check(slow, 4096)
    assert result.status == "error"
    assert result.reason == "timed out after 1s"
    assert result.duration_s == 1.0


def test_output_is_bounded_and_marked_truncated():
    chatty = spec([PY, "-c", "print('x' * 100000)"])
    result = run_check(chatty, 100)
    assert "output truncated at 100 bytes" in result.stdout
    assert len(result.stdout) < 200


def test_captured_output_is_redacted():
    token = "ghp_" + "a" * 36
    leaky = spec([PY, "-c", f"print('token={token}')"])
    result = run_check(leaky, 4096)
    assert token not in result.stdout
    assert "[REDACTED]" in result.stdout


def test_failed_start_is_error(tmp_path):
    bad = spec([PY, "-c", "pass"], cwd=str(tmp_path / "missing-dir"))
    result = run_check(bad, 4096)
    assert result.status == "error"
    assert result.reason is not None and "failed to start" in result.reason


def test_stderr_is_captured():
    noisy = spec([PY, "-c", "import sys; sys.stderr.write('boom\\n'); sys.exit(1)"])
    result = run_check(noisy, 4096)
    assert result.status == "failed"
    assert "boom" in result.stderr
