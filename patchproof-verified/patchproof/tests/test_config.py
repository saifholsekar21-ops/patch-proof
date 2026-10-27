"""Tests for configuration loading and validation (patchproof.config)."""

from __future__ import annotations

import pytest

from patchproof.config import ConfigError, load_config


def write_config(tmp_path, text: str) -> str:
    path = tmp_path / "patchproof.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_defaults_when_no_path():
    config = load_config(None)
    assert config.checks.required == ["tests", "secrets"]
    assert config.checks.optional == ["lint", "typecheck", "deps"]
    assert config.limits.timeout_s == 300.0
    assert config.limits.output_limit_bytes == 32768
    assert config.git.selection == "working"
    assert config.report.format == "json"
    assert config.report.redact is True
    assert config.secrets.enabled is True


def test_full_config_parsed(tmp_path):
    path = write_config(
        tmp_path,
        """
[checks]
required = ["tests"]
optional = ["lint"]

[checks.tests]
command = ["python", "-m", "pytest", "-q"]

[[checks.custom]]
name = "greet"
command = ["python", "-c", "print('hi')"]
required = true
timeout_s = 5

[limits]
timeout_s = 60
output_limit_bytes = 1000

[git]
selection = "staged"
base = "main~1"
head = "main"

[report]
format = "markdown"
destination = "report.md"
redact = false

[secrets]
max_files = 100
""",
    )
    config = load_config(path)
    assert config.checks.required == ["tests"]
    assert config.checks.optional == ["lint"]
    assert config.checks.tests.command == ["python", "-m", "pytest", "-q"]
    custom = config.checks.custom[0]
    assert custom.name == "greet"
    assert custom.required is True
    assert custom.timeout_s == 5.0
    assert config.limits.timeout_s == 60.0
    assert config.limits.output_limit_bytes == 1000
    assert config.git.selection == "staged"
    assert config.git.base == "main~1"
    assert config.report.format == "markdown"
    assert config.report.destination == "report.md"
    assert config.report.redact is False
    assert config.secrets.max_files == 100


INVALID_CONFIGS = [
    "not valid toml [",
    '[checks]\nrequired = ["wat"]\n',
    '[checks]\nrequired = ["tests", "tests"]\n',
    '[checks]\nrequired = ["tests"]\noptional = ["tests"]\n',
    "[checks]\nextra_key = 1\n",
    '[checks.tests]\ncommand = ["python", "-c", "pass"]\nextra_key = 1\n',
    '[git]\nselection = "bogus"\n',
    '[report]\nformat = "yaml"\n',
    "[limits]\ntimeout_s = 0\n",
    "[limits]\noutput_limit_bytes = -5\n",
    "[checks.tests]\ncommand = []\n",
    '[checks.tests]\ncommand = [""]\n',
    '[[checks.custom]]\nname = "bad name"\ncommand = ["python"]\n',
    '[[checks.custom]]\nname = "ok"\ncommand = []\n',
]


@pytest.mark.parametrize("text", INVALID_CONFIGS)
def test_invalid_configs_rejected(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, text))


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="cannot read config file"):
        load_config(str(tmp_path / "nope.toml"))


def test_empty_config_uses_defaults(tmp_path):
    config = load_config(write_config(tmp_path, "\n"))
    assert config.checks.required == ["tests", "secrets"]
