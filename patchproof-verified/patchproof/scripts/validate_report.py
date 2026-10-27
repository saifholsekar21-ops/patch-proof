#!/usr/bin/env python3
"""Validate a PatchProof verification report (JSON) against the report contract.

Backward-compatible entry point. The canonical validator now lives in the
installable package (src/patchproof/validate.py); this script delegates to it
so the original standalone workflow keeps working.

Usage:
    python validate_report.py path/to/report.json
    python validate_report.py path/to/report.json --json
    python validate_report.py path/to/report.json --redact-output clean.json

Exit codes:
    0  report is valid (warnings allowed)
    1  report is invalid
    2  usage or I/O error (missing file, unreadable file, malformed JSON)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the src/ package importable when this script is run directly (not via
# the installed package). Safe to call even when already importable.
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from patchproof.secrets import (  # noqa: E402
    find_secrets_in_string,
    redact_report,
    redact_text,
)
from patchproof.validate import (  # noqa: E402
    CHECK_STATUSES_V10,
    CHECK_STATUSES_V11,
    FINDING_SEVERITIES,
    FINDING_STATUSES,
    LATEST_SCHEMA_VERSION,
    OVERALL_STATUSES,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    VERIFICATION_STATUSES,
    ReportLoadError,
    build_parser,
    load_report,
    main,
    validate_report,
)

__all__ = [
    "CHECK_STATUSES_V10",
    "CHECK_STATUSES_V11",
    "FINDING_SEVERITIES",
    "FINDING_STATUSES",
    "LATEST_SCHEMA_VERSION",
    "OVERALL_STATUSES",
    "ReportLoadError",
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "VERIFICATION_STATUSES",
    "build_parser",
    "find_secrets_in_string",
    "load_report",
    "main",
    "redact_report",
    "redact_text",
    "validate_report",
]

if __name__ == "__main__":
    sys.exit(main())
