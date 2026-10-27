"""Tests for CLI commands and stable exit codes (in-process via cli.main)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import gitutil
import pytest
import typer

from patchproof import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_help_exits_zero(capsys):
    assert cli.main(["--help"]) == cli.EXIT_PASSED
    assert "Usage" in capsys.readouterr().out


def test_version_exits_zero(capsys):
    assert cli.main(["--version"]) == cli.EXIT_PASSED
    assert "patchproof" in capsys.readouterr().out


def test_bare_invocation_is_usage_error(capsys):
    assert cli.main([]) == cli.EXIT_USAGE
    capsys.readouterr()


def test_unknown_option_is_usage_error(capsys):
    assert cli.main(["verify", "--definitely-not-an-option"]) == cli.EXIT_USAGE
    capsys.readouterr()


def test_inspect_on_directory(tmp_path, capsys):
    assert cli.main(["inspect", str(tmp_path)]) == cli.EXIT_PASSED
    assert "repository" in capsys.readouterr().out


def test_verify_missing_directory_is_usage_error(capsys):
    assert cli.main(["verify", "definitely_missing_dir_12345"]) == cli.EXIT_USAGE
    capsys.readouterr()


def test_verify_non_git_directory_requires_select_none(tmp_path, capsys):
    assert cli.main(["verify", str(tmp_path)]) == cli.EXIT_USAGE
    assert "not a git repository" in capsys.readouterr().err


def test_verify_non_git_directory_with_select_none_runs(tmp_path, capsys):
    code = cli.main(["verify", str(tmp_path), "--select", "none", "--format", "json"])
    assert code == cli.EXIT_UNVERIFIED
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_status"] == "unverified"
    assert payload["selection_policy"] == "none"


def test_verify_bad_format_is_usage_error(tmp_path, capsys):
    assert (
        cli.main(["verify", str(tmp_path), "--select", "none", "--format", "yaml"])
        == cli.EXIT_USAGE
    )
    capsys.readouterr()


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--definitely-not-an-option"],
        ["verify", "definitely_missing_dir_12345"],
        ["verify", "definitely_missing_dir_12345", "--format", "yaml"],
        ["report"],
        ["report", str(FIXTURES / "valid_report.json"), "--format", "yaml"],
        ["config"],
    ],
)
def test_usage_errors_report_without_traceback(argv, capsys):
    assert cli.main(argv) == cli.EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.err.strip()
    assert "Traceback" not in captured.err


def test_usage_error_types_exclude_control_flow_exceptions():
    types = cli._usage_error_types()
    assert types
    assert any(issubclass(typer.BadParameter, candidate) for candidate in types)
    for control_flow in (typer.Exit, typer.Abort):
        assert not any(issubclass(control_flow, candidate) for candidate in types)


def test_unexpected_programming_errors_are_not_swallowed(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "app", explode)
    with pytest.raises(RuntimeError, match="boom"):
        cli.main([])


def test_config_validate_defaults(capsys):
    assert cli.main(["config", "validate"]) == cli.EXIT_PASSED
    assert "VALID" in capsys.readouterr().out


def test_config_validate_invalid_toml(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("not valid [", encoding="utf-8")
    assert cli.main(["config", "validate", "--config", str(bad)]) == cli.EXIT_FAILED
    assert "INVALID" in capsys.readouterr().out


def test_config_validate_redacts_override_commands(tmp_path, capsys):
    token = "ghp_" + "a" * 36
    config = tmp_path / "cfg.toml"
    config.write_text(
        f'[checks.tests]\ncommand = ["python", "-c", "{token}"]\n', encoding="utf-8"
    )
    assert cli.main(["config", "validate", "--config", str(config)]) == cli.EXIT_PASSED
    out = capsys.readouterr().out
    assert token not in out
    assert "[REDACTED]" in out


def test_report_renders_legacy_fixture(capsys):
    code = cli.main(["report", str(FIXTURES / "valid_report.json"), "--format", "json"])
    assert code == cli.EXIT_PASSED
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.1"
    assert payload["checks"][0]["status"] == "passed"


def test_report_malformed_fixture_is_usage_error(capsys):
    assert cli.main(["report", str(FIXTURES / "malformed_report.json")]) == cli.EXIT_USAGE
    capsys.readouterr()


def test_report_missing_file_is_usage_error(capsys):
    assert cli.main(["report", "definitely_missing_report_12345.json"]) == cli.EXIT_USAGE
    capsys.readouterr()


def test_report_bad_format_is_usage_error(capsys):
    code = cli.main(["report", str(FIXTURES / "valid_report.json"), "--format", "yaml"])
    assert code == cli.EXIT_USAGE
    capsys.readouterr()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_verify_bad_selection_is_usage_error(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    assert cli.main(["verify", str(root), "--select", "bogus"]) == cli.EXIT_USAGE
    capsys.readouterr()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_verify_writes_report_to_output_file(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    gitutil.init_repo(root)
    config = tmp_path / "cfg.toml"
    config.write_text(
        "[checks]\nrequired = []\noptional = []\n\n[secrets]\nenabled = false\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    code = cli.main(
        [
            "verify",
            str(root),
            "--select",
            "none",
            "--format",
            "json",
            "--output",
            str(output),
            "--config",
            str(config),
        ]
    )
    assert code == cli.EXIT_UNVERIFIED
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.1"
    assert "report written to" in capsys.readouterr().out
