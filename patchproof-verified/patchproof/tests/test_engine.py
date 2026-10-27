"""Tests for verification orchestration (patchproof.engine)."""

from __future__ import annotations

import sys

from patchproof.config import PatchProofConfig
from patchproof.engine import run_verification
from patchproof.repo import ChangeSet

PY = sys.executable


def make_config(data: dict) -> PatchProofConfig:
    return PatchProofConfig.model_validate(data)


def no_changes() -> ChangeSet:
    return ChangeSet(selection="none")


def test_secrets_check_passes_on_clean_tree(tmp_path):
    config = make_config({"checks": {"required": ["secrets"], "optional": []}})
    report = run_verification(str(tmp_path), config, no_changes())
    assert report.overall_status == "passed"
    secrets = [check for check in report.checks if check.id == "secrets"]
    assert secrets and secrets[0].status == "passed"


def test_secrets_check_fails_on_planted_token(tmp_path):
    # Assembled from fragments so this repository's own secret scan stays clean.
    planted = "AKIA" + "IOSFODNN7EXAMPLE"
    (tmp_path / "leak.txt").write_text(planted + "\n", encoding="utf-8")
    config = make_config({"checks": {"required": ["secrets"], "optional": []}})
    report = run_verification(str(tmp_path), config, no_changes())
    assert report.overall_status == "failed"
    assert "AKIA" not in report.findings[0].evidence[0]


def test_custom_checks_execute_and_drive_status(tmp_path):
    config = make_config(
        {
            "checks": {
                "required": [],
                "optional": [],
                "custom": [
                    {"name": "ok", "command": [PY, "-c", "print('ok')"], "required": True},
                    {
                        "name": "boom",
                        "command": [PY, "-c", "import sys; sys.exit(2)"],
                        "required": True,
                    },
                ],
            },
            "secrets": {"enabled": False},
        }
    )
    report = run_verification(str(tmp_path), config, no_changes())
    by_id = {check.id: check for check in report.checks}
    assert by_id["custom:ok"].status == "passed"
    assert by_id["custom:boom"].status == "failed"
    assert by_id["custom:boom"].exit_code == 2
    assert report.overall_status == "failed"


def test_check_ordering_is_deterministic(tmp_path):
    config = make_config(
        {
            "checks": {
                "required": ["tests"],
                "optional": ["lint"],
                "tests": {"command": [PY, "-c", "pass"]},
                "lint": {"command": [PY, "-c", "pass"]},
                "custom": [
                    {"name": "z", "command": [PY, "-c", "pass"], "required": False},
                    {"name": "a", "command": [PY, "-c", "pass"], "required": False},
                ],
            }
        }
    )
    report = run_verification(str(tmp_path), config, no_changes())
    assert [check.id for check in report.checks] == [
        "tests",
        "lint",
        "secrets",
        "custom:z",
        "custom:a",
    ]


def test_missing_required_tool_is_error(tmp_path):
    config = make_config(
        {
            "checks": {
                "required": ["tests"],
                "optional": [],
                "tests": {"command": ["definitely-not-a-real-tool-xyz"]},
            },
            "secrets": {"enabled": False},
        }
    )
    report = run_verification(str(tmp_path), config, no_changes())
    assert report.overall_status == "error"
    tests = [check for check in report.checks if check.id == "tests"][0]
    assert tests.status == "error"
    assert tests.reason is not None and "not found" in tests.reason


def test_missing_optional_tool_is_skipped_not_passed(tmp_path):
    config = make_config(
        {
            "checks": {
                "required": [],
                "optional": ["lint"],
                "lint": {"command": ["definitely-not-a-real-tool-xyz"]},
            },
            "secrets": {"enabled": False},
        }
    )
    report = run_verification(str(tmp_path), config, no_changes())
    lint = [check for check in report.checks if check.id == "lint"][0]
    assert lint.status == "skipped"
    assert lint.required is False
    assert report.overall_status == "unverified"


def test_unresolved_required_check_is_unverified(tmp_path):
    config = make_config({"checks": {"required": ["tests"], "optional": []}})
    report = run_verification(str(tmp_path), config, no_changes())
    assert report.overall_status == "unverified"
    tests = [check for check in report.checks if check.id == "tests"][0]
    assert tests.status == "unverified"
    assert tests.command == "(not configured)"
    assert tests.reason is not None and "override" in tests.reason


def test_custom_check_timeout_is_error(tmp_path):
    config = make_config(
        {
            "checks": {
                "required": [],
                "optional": [],
                "custom": [
                    {
                        "name": "slow",
                        "command": [PY, "-c", "import time; time.sleep(60)"],
                        "required": True,
                        "timeout_s": 1,
                    }
                ],
            },
            "secrets": {"enabled": False},
        }
    )
    report = run_verification(str(tmp_path), config, no_changes())
    slow = [check for check in report.checks if check.id == "custom:slow"][0]
    assert slow.status == "error"
    assert slow.reason is not None and "timed out" in slow.reason
    assert report.overall_status == "error"


def test_output_limit_truncates_through_engine(tmp_path):
    config = make_config(
        {
            "checks": {
                "required": [],
                "optional": [],
                "custom": [
                    {
                        "name": "chatty",
                        "command": [PY, "-c", "print('x' * 100000)"],
                        "required": True,
                    }
                ],
            },
            "limits": {"output_limit_bytes": 100},
            "secrets": {"enabled": False},
        }
    )
    report = run_verification(str(tmp_path), config, no_changes())
    chatty = [check for check in report.checks if check.id == "custom:chatty"][0]
    assert "output truncated at 100 bytes" in chatty.stdout


def test_report_carries_limitations_and_self_validates(tmp_path):
    config = make_config({"checks": {"required": [], "optional": []}})
    change_set = ChangeSet(selection="working", notes=["note one"])
    report = run_verification(str(tmp_path), config, change_set)
    assert "note one" in report.limitations
    assert any("no sandboxing" in item for item in report.limitations)
    assert any("no language configuration" in item for item in report.limitations)
