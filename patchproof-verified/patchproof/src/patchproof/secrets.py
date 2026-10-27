"""Credential detection and redaction for PatchProof.

Regex-based scanning is inherently limited: it catches well-known patterns
but cannot find novel or heavily obfuscated credentials. It is a defensive
layer, not a guarantee. Documented limitations live in SECURITY.md.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any

# Values that the generic assignment pattern must never flag. Kept short and
# explicit; adding a value here trades a potential false negative for fewer
# false positives.
_PLACEHOLDER_VALUES = frozenset(
    {
        "undefined",
        "null",
        "none",
        "example",
        "placeholder",
        "changeme",
        "password",
        "secret",
        "yourpassword",
        "testvalue",
        "redacted",
        "xxxxxx",
        "12345678",
    }
)

_Pattern = tuple[re.Pattern, str, Callable[[re.Match], str]]

_SECRET_PATTERNS: Sequence[_Pattern] = (
    # AWS access key id
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws_access_key", lambda m: "[REDACTED]"),
    # AWS secret access key: 40 base64-ish chars. The second lookahead
    # requires at least one non-hex character so pure-hex strings (git
    # SHAs, MD5s) are never flagged; random base64 of this length virtually
    # always contains one.
    (
        re.compile(
            r"\b(?=[A-Za-z0-9/+]{40}\b)"
            r"(?=[A-Za-z0-9/+]*[g-zG-Z+/])"
            r"[A-Za-z0-9/+]{40}\b"
        ),
        "aws_secret_key",
        lambda m: "[REDACTED]",
    ),
    # GitHub tokens: classic (ghp/gho/ghu/ghs + 36), fine-grained (github_pat_ + 82), ghx (40)
    (
        re.compile(r"\bgh[pous]_[A-Za-z0-9]{36}\b"),
        "github_token",
        lambda m: "[REDACTED]",
    ),
    (
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b"),
        "github_fine_grained_token",
        lambda m: "[REDACTED]",
    ),
    (
        re.compile(r"\bghx_[A-Za-z0-9]{40}\b"),
        "github_ghx_token",
        lambda m: "[REDACTED]",
    ),
    # Slack tokens
    (
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        "slack_token",
        lambda m: "[REDACTED]",
    ),
    # Stripe live keys
    (
        re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{10,}\b"),
        "stripe_live_key",
        lambda m: "[REDACTED]",
    ),
    # Google API keys
    (
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        "google_api_key",
        lambda m: "[REDACTED]",
    ),
    # JSON Web Tokens (header.payload.signature)
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
        "jwt",
        lambda m: "[REDACTED]",
    ),
    # PEM private key blocks
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----"
            r".*?"
            r"-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----",
            re.DOTALL,
        ),
        "private_key_block",
        lambda m: "[REDACTED PRIVATE KEY]",
    ),
    # Bearer authorization headers
    (
        re.compile(r"\bBearer [A-Za-z0-9._\-]{20,}\b"),
        "bearer_token",
        lambda m: "Bearer [REDACTED]",
    ),
    # Generic assignments: key=value / key: value
    (
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|secret|passwd|password|token|auth_token|"
            r"access[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+]{8,})['\"]?"
        ),
        "credential_assignment",
        lambda m: (
            m.group(0)[: m.start(2) - m.start(0)] + "[REDACTED]"
            if m.group(2).lower() not in _PLACEHOLDER_VALUES
            else m.group(0)
        ),
    ),
)


def iter_secret_matches(text: str) -> Iterator[tuple[str, re.Match]]:
    """Yield (kind, match) for every detected secret pattern in *text*.

    Matches whose replacement keeps the original text (placeholder values on
    the denylist) are treated as non-secrets and skipped, keeping detection
    and redaction consistent.
    """
    for pattern, kind, replacement in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if replacement(match) != match.group(0):
                yield kind, match


def find_secrets_in_string(text: str, path: str = "$") -> list[dict[str, str]]:
    """Return [{"path", "kind"}] for secret material found in *text*.

    The matched value is deliberately never included, so callers cannot echo
    the secret they detected.
    """
    found: list[dict[str, str]] = []
    if not isinstance(text, str):
        return found
    for kind, _match in iter_secret_matches(text):
        found.append({"path": path, "kind": kind})
    return found


def redact_text(text: str) -> str:
    """Return *text* with detected secret material replaced by placeholders.

    Never raises; non-strings and empty strings are returned unchanged.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        for pattern, _kind, replacement in _SECRET_PATTERNS:
            text = pattern.sub(replacement, text)
    except (re.error, TypeError):
        pass
    return text


def redact_report(data: Any) -> Any:
    """Deep-copy *data* with secret material in all strings masked."""
    if isinstance(data, dict):
        return {key: redact_report(value) for key, value in data.items()}
    if isinstance(data, list):
        return [redact_report(item) for item in data]
    if isinstance(data, str):
        return redact_text(data)
    return data
