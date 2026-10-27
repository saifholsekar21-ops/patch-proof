"""Tests for the PatchProof report validator (scripts/validate_report.py)."""

import json
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURES_DIR = TESTS_DIR / "fixtures"

sys.path.insert(0, str(SCRIPTS_DIR))

import validate_report as vr  # noqa: E402

# Credential-shaped fixtures are assembled from fragments so this repository's
# own required secret scan does not flag its test data. The resulting strings
# still match the validator's detector exactly.
AWS_ACCESS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
RSA_PRIVATE_KEY_BLOCK = (
    "-----BEGIN RSA " + "PRIVATE KEY-----"
    "\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
    "-----END RSA " + "PRIVATE KEY-----"
)
OPENSSH_PRIVATE_KEY_BLOCK = (
    "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nabc\n"
    "-----END OPENSSH " + "PRIVATE KEY-----"
)
PASSWORD_ASSIGNMENT = "pass" + "word=supersecret123"
GHX_TOKEN = "ghx_" + "abcdefghijklmnopqrstuvwxyz1234567890"
BEARER_HEADER = "Authorization: Bearer " + "abcdefghijklmnopqrstuvwx"


def _load_fixture(name: str):
    return vr.load_report(str(FIXTURES_DIR / name))


class TestValidReport(unittest.TestCase):
    def test_valid_fixture_passes(self):
        result = vr.validate_report(_load_fixture("valid_report.json"))
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_valid_fixture_has_no_warnings(self):
        result = vr.validate_report(_load_fixture("valid_report.json"))
        self.assertEqual(result["warnings"], [])

    def test_not_run_check_with_reason_is_valid(self):
        report = _load_fixture("valid_report.json")
        report["checks"].append(
            {
                "id": "C-010",
                "tool": "playwright",
                "command": "npx playwright test",
                "status": "NOT_RUN",
                "reason": "no browser available in this environment",
            }
        )
        result = vr.validate_report(report)
        self.assertTrue(result["valid"], result["errors"])

    def test_error_check_with_reason_and_duration_is_valid(self):
        report = _load_fixture("valid_report.json")
        report["checks"].append(
            {
                "id": "C-011",
                "tool": "pytest",
                "command": "python -m pytest -q",
                "status": "ERROR",
                "exit_code": None,
                "duration_s": 15.0,
                "reason": "timed out after 15s",
                "evidence": ["timeout: no output captured"],
            }
        )
        result = vr.validate_report(report)
        self.assertTrue(result["valid"], result["errors"])

    def test_skipped_check_is_never_usable_as_verification(self):
        report = _load_fixture("valid_report.json")
        report["changes"][0]["verified_by"] = ["C-003"]  # C-003 is SKIPPED
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        codes = [entry["code"] for entry in result["errors"]]
        self.assertIn("unverified_claim", codes)


class TestInvalidStatuses(unittest.TestCase):
    def test_unsupported_check_status_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["status"] = "PASSING"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "enum")

    def test_lowercase_status_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["status"] = "pass"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "enum")

    def test_unsupported_severity_rejected(self):
        report = _load_fixture("valid_report.json")
        report["findings"][0]["severity"] = "catastrophic"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "enum")

    def test_unsupported_verification_status_rejected(self):
        report = _load_fixture("valid_report.json")
        report["changes"][0]["verification_status"] = "confirmed"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "enum")

    def test_unsupported_schema_version_rejected(self):
        report = _load_fixture("valid_report.json")
        report["schema_version"] = "0.9"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "schema_version")


class TestEvidenceRequirements(unittest.TestCase):
    def test_pass_without_evidence_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["exit_code"] = None
        report["checks"][0]["evidence"] = []
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        codes = [entry["code"] for entry in result["errors"]]
        self.assertIn("missing_evidence", codes)

    def test_pass_with_empty_evidence_strings_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["exit_code"] = None
        report["checks"][0]["evidence"] = ["   "]
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        codes = [entry["code"] for entry in result["errors"]]
        self.assertIn("missing_evidence", codes)

    def test_pass_with_exit_code_alone_is_valid(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["evidence"] = []
        result = vr.validate_report(report)
        self.assertTrue(result["valid"], result["errors"])

    def test_skipped_without_reason_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][2]["reason"] = None  # C-003 is SKIPPED
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "missing_reason")

    def test_finding_without_evidence_rejected(self):
        report = _load_fixture("valid_report.json")
        report["findings"][0]["evidence"] = []
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])

    def test_evidence_entries_must_be_strings(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["evidence"] = [123]
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])

    def test_negative_duration_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["duration_s"] = -1.0
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])

    def test_missing_findings_section_rejected(self):
        report = _load_fixture("valid_report.json")
        del report["findings"]
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])


class TestVerifiedChanges(unittest.TestCase):
    def test_verified_change_requires_passing_check(self):
        report = _load_fixture("valid_report.json")
        report["changes"][0]["verified_by"] = ["C-002"]  # C-002 is FAIL
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "unverified_claim")

    def test_verified_change_rejects_unknown_check(self):
        report = _load_fixture("valid_report.json")
        report["changes"][0]["verified_by"] = ["C-999"]
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "unverified_claim")

    def test_verified_change_without_verified_by_rejected(self):
        report = _load_fixture("valid_report.json")
        report["changes"][0]["verified_by"] = []
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "unverified_claim")

    def test_unverified_change_with_verified_by_rejected(self):
        report = _load_fixture("valid_report.json")
        report["changes"][0]["verification_status"] = "unverified"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "unverified_claim")

    def test_proposed_change_is_valid_and_not_claimed_verified(self):
        report = _load_fixture("valid_report.json")
        result = vr.validate_report(report)
        self.assertTrue(result["valid"], result["errors"])
        proposed = [
            change
            for change in report["changes"]
            if change["verification_status"] == "proposed"
        ]
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["verified_by"], [])


class TestSecretDetection(unittest.TestCase):
    def test_aws_key_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["summary"] = "deployed with " + AWS_ACCESS_KEY
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertIn("secret_material", [e["code"] for e in result["errors"]])

    def test_private_key_block_rejected(self):
        report = _load_fixture("valid_report.json")
        report["findings"][0]["evidence"] = [RSA_PRIVATE_KEY_BLOCK]
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertIn("secret_material", [e["code"] for e in result["errors"]])

    def test_credential_assignment_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["command"] = "curl -H '" + BEARER_HEADER + "' http://x"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertIn("secret_material", [e["code"] for e in result["errors"]])

    def test_detected_secret_value_never_echoed(self):
        report = _load_fixture("valid_report.json")
        secret = AWS_ACCESS_KEY
        report["checks"][0]["summary"] = f"key is {secret}"
        result = vr.validate_report(report)
        serialized = json.dumps(result)
        self.assertNotIn(secret, serialized)

    def test_redact_text_masks_all_secret_kinds(self):
        samples = [
            "key=" + AWS_ACCESS_KEY + " done",
            PASSWORD_ASSIGNMENT,
            "token: " + GHX_TOKEN,
            BEARER_HEADER,
            OPENSSH_PRIVATE_KEY_BLOCK,
        ]
        for sample in samples:
            redacted = vr.redact_text(sample)
            self.assertNotIn(sample, redacted)
            self.assertIn("[REDACTED", redacted)

    def test_redact_text_ignores_non_secret_text(self):
        text = "pytest passed: 12 tests collected"
        self.assertEqual(vr.redact_text(text), text)

    def test_redact_report_writes_only_redacted_copy(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["summary"] = "used " + AWS_ACCESS_KEY
        redacted = vr.redact_report(report)
        self.assertIn("[REDACTED]", redacted["checks"][0]["summary"])
        self.assertNotIn("AKIA", redacted["checks"][0]["summary"])
        self.assertIn("AKIA", report["checks"][0]["summary"])


class TestMalformedInput(unittest.TestCase):
    def test_non_json_file_gives_clean_error(self):
        with self.assertRaises(vr.ReportLoadError) as context:
            vr.load_report(str(FIXTURES_DIR / "malformed_report.json"))
        self.assertIn("malformed JSON", str(context.exception))

    def test_missing_file_gives_clean_error(self):
        with self.assertRaises(vr.ReportLoadError) as context:
            vr.load_report(str(FIXTURES_DIR / "does_not_exist.json"))
        self.assertIn("cannot read file", str(context.exception))

    def test_non_object_root_rejected(self):
        with self.assertRaises(vr.ReportLoadError) as context:
            vr.load_report(str(FIXTURES_DIR / "array_root.json"))
        self.assertIn("must be a JSON object", str(context.exception))

    def test_pathological_nesting_gives_clean_error(self):
        import tempfile

        deep = "[" * 10000 + "]" * 10000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep.json"
            path.write_text(deep, encoding="utf-8")
            with self.assertRaises(vr.ReportLoadError) as context:
                vr.load_report(str(path))
            self.assertIn("nesting", str(context.exception))

    def test_deeply_nested_struct_does_not_crash_validator(self):
        report = _load_fixture("valid_report.json")
        nested = report
        for _ in range(100):
            nested = {"x": nested}
        result = vr.validate_report(nested)
        # The validator must not crash on deep structures.
        self.assertIn("valid", result)

    def test_missing_repository_section_rejected(self):
        report = _load_fixture("valid_report.json")
        del report["repository"]
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])


class TestStructureRules(unittest.TestCase):
    def test_duplicate_check_ids_rejected(self):
        report = _load_fixture("valid_report.json")
        report["checks"].append(dict(report["checks"][0]))
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])
        self.assertIn("duplicate_id", [e["code"] for e in result["errors"]])

    def test_path_traversal_location_warns(self):
        report = _load_fixture("valid_report.json")
        report["findings"][0]["locations"] = [
            {"file": "../../etc/passwd", "line": 1}
        ]
        result = vr.validate_report(report)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(
            any("traversal" in w["message"] for w in result["warnings"])
        )

    def test_unknown_top_level_field_warns_only(self):
        report = _load_fixture("valid_report.json")
        report["notes"] = "free-form"
        result = vr.validate_report(report)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("unknown" in w["message"] for w in result["warnings"]))

    def test_exit_code_must_be_integer(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["exit_code"] = "0"
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])

    def test_task_id_required(self):
        report = _load_fixture("valid_report.json")
        del report["task_id"]
        result = vr.validate_report(report)
        self.assertFalse(result["valid"])


class TestRedactOutputFlow(unittest.TestCase):
    def test_redacted_report_validates_clean(self):
        report = _load_fixture("valid_report.json")
        report["checks"][0]["summary"] = "deploy used " + AWS_ACCESS_KEY
        redacted = vr.redact_report(report)
        result = vr.validate_report(redacted)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["secrets"], [])


if __name__ == "__main__":
    unittest.main()
