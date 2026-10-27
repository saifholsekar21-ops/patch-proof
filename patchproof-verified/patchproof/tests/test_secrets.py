"""False-positive / false-negative regression tests for secret detection and redaction."""

from __future__ import annotations

import json

import pytest

from patchproof.checks.secretscan import scan_repository_secrets
from patchproof.secrets import (
    find_secrets_in_string,
    iter_secret_matches,
    redact_report,
    redact_text,
)

# Credential-shaped fixtures are assembled from fragments so this repository's
# own required secret scan does not flag its test data. The resulting strings
# still match the detector exactly.
AWS_ACCESS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
PRIVATE_KEY_BLOCK = (
    "-----BEGIN " + "PRIVATE KEY-----" + "\nabc\n" + "-----END " + "PRIVATE KEY-----"
)
CREDENTIAL_ASSIGNMENT = "pass" + "word=" + "hunter2" + "secret"

DETECTIONS = [
    ("aws_access_key", AWS_ACCESS_KEY),
    ("aws_secret_key", "a" * 39 + "z"),
    ("github_token", "ghp_" + "a" * 36),
    ("github_fine_grained_token", "github_pat_" + "a" * 82),
    ("github_ghx_token", "ghx_" + "a" * 40),
    ("slack_token", "xoxb-" + "a" * 10),
    ("stripe_live_key", "sk_live_" + "a" * 10),
    ("google_api_key", "AIza" + "a" * 35),
    ("jwt", "eyJ" + "a" * 5 + ".eyJ" + "b" * 5 + ".ccccc"),
    ("private_key_block", PRIVATE_KEY_BLOCK),
    ("bearer_token", "Bearer " + "a" * 20),
    ("credential_assignment", CREDENTIAL_ASSIGNMENT),
]


@pytest.mark.parametrize("kind,text", DETECTIONS)
def test_known_patterns_are_detected(kind, text):
    kinds = [found_kind for found_kind, _match in iter_secret_matches(text)]
    assert kind in kinds


PLACEHOLDERS = [
    "password=changeme",
    "password=password",
    "api_key=12345678",
    "token=redacted",
    "secret=placeholder",
    "api_key=xxxxxx",
]


@pytest.mark.parametrize("text", PLACEHOLDERS)
def test_placeholder_values_are_not_flagged(text):
    assert find_secrets_in_string(text) == []


def test_pure_hex_string_is_not_an_aws_secret():
    assert find_secrets_in_string("a" * 40) == []


def test_short_github_prefix_is_not_flagged():
    assert find_secrets_in_string("ghp_short") == []


def test_find_secrets_never_returns_the_matched_value():
    token = "ghp_" + "a" * 36
    found = find_secrets_in_string(f"export TOKEN={token}")
    kinds = [entry["kind"] for entry in found]
    assert "github_token" in kinds
    assert token not in json.dumps(found)


def test_redact_text_masks_value_but_keeps_context():
    text = "export GITHUB_TOKEN=ghp_" + "a" * 36
    redacted = redact_text(text)
    assert "ghp_" not in redacted
    assert "[REDACTED]" in redacted
    assert redacted.startswith("export GITHUB_TOKEN=")


def test_redact_text_handles_empty_and_non_strings():
    assert redact_text("") == ""
    assert redact_text(None) is None  # type: ignore[arg-type]  # runtime tolerance


def test_redact_report_deep_masks_nested_structures():
    data = {"a": [{"b": "key=ghp_" + "a" * 36}], "c": 5, "d": None}
    masked = redact_report(data)
    assert "ghp_" not in json.dumps(masked)
    assert masked["c"] == 5
    assert masked["d"] is None


def test_scan_finds_leaks_with_redacted_evidence(tmp_path):
    (tmp_path / "leak.py").write_text(AWS_ACCESS_KEY + "\n", encoding="utf-8")
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    findings = scan_repository_secrets(str(tmp_path))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.locations[0].file == "leak.py"
    assert finding.locations[0].line == 1
    assert "AKIA" not in finding.evidence[0]
    assert "[REDACTED]" in finding.evidence[0]


def test_scan_skips_binary_and_vendored_files(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01" + AWS_ACCESS_KEY.encode())
    vendored = tmp_path / "node_modules"
    vendored.mkdir()
    (vendored / "dep.js").write_text(AWS_ACCESS_KEY + "\n", encoding="utf-8")
    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    (gitdir / "config").write_text(AWS_ACCESS_KEY + "\n", encoding="utf-8")
    assert scan_repository_secrets(str(tmp_path)) == []


def test_scan_respects_file_cap(tmp_path):
    for index in range(5):
        (tmp_path / f"f{index}.txt").write_text("clean\n", encoding="utf-8")
    assert scan_repository_secrets(str(tmp_path), max_files=2) == []


def test_scan_respects_size_cap(tmp_path):
    (tmp_path / "big.txt").write_text(
        AWS_ACCESS_KEY + "\n" + "x" * 1000, encoding="utf-8"
    )
    assert scan_repository_secrets(str(tmp_path), max_file_bytes=10) == []


def test_scan_reports_line_numbers(tmp_path):
    (tmp_path / "multi.txt").write_text(
        "clean line\nanother\n" + AWS_ACCESS_KEY + "\n", encoding="utf-8"
    )
    findings = scan_repository_secrets(str(tmp_path))
    assert findings[0].locations[0].line == 3
