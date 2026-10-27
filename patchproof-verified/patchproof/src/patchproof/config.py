"""Configuration loading and validation for PatchProof.

Configuration files are TOML (stdlib tomllib). All check commands are
argument arrays — there is no shell interpretation and never will be.
Custom checks are executable code configured explicitly by the user;
PatchProof never generates them.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import CHECK_CATEGORIES
from .repo import SELECTIONS

DEFAULT_REQUIRED = ["tests", "secrets"]
DEFAULT_OPTIONAL = ["lint", "typecheck", "deps"]


class ConfigError(Exception):
    """The configuration file is missing, malformed, or invalid."""


class CheckOverride(BaseModel):
    """Explicit command override for a built-in check category."""

    model_config = ConfigDict(extra="forbid")

    command: list[str] | None = None

    @field_validator("command")
    @classmethod
    def _non_empty_argv(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("command must be a non-empty list of non-empty strings")
        return value


class CustomCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    command: list[str]
    required: bool = False
    timeout_s: float | None = None

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        if not all(ch.isalnum() or ch in "-_" for ch in value):
            raise ValueError("name may only contain letters, digits, '-' and '_'")
        return value

    @field_validator("command")
    @classmethod
    def _non_empty_argv(cls, value: list[str]) -> list[str]:
        if not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("command must be a non-empty list of non-empty strings")
        return value


class ChecksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=lambda: list(DEFAULT_REQUIRED))
    optional: list[str] = Field(default_factory=lambda: list(DEFAULT_OPTIONAL))
    tests: CheckOverride = Field(default_factory=CheckOverride)
    lint: CheckOverride = Field(default_factory=CheckOverride)
    typecheck: CheckOverride = Field(default_factory=CheckOverride)
    deps: CheckOverride = Field(default_factory=CheckOverride)
    custom: list[CustomCheck] = Field(default_factory=list)

    @field_validator("required", "optional")
    @classmethod
    def _known_categories(cls, value: list[str]) -> list[str]:
        for category in value:
            if category not in CHECK_CATEGORIES:
                raise ValueError(
                    f"unknown check category {category!r}; expected one of "
                    + ", ".join(CHECK_CATEGORIES)
                )
        return value

    @model_validator(mode="after")
    def _no_overlap(self) -> ChecksConfig:
        overlap = set(self.required) & set(self.optional)
        if overlap:
            raise ValueError(
                f"categories listed as both required and optional: {sorted(overlap)}"
            )
        for label, entries in (("required", self.required), ("optional", self.optional)):
            duplicates = sorted({entry for entry in entries if entries.count(entry) > 1})
            if duplicates:
                raise ValueError(f"duplicate categories in {label}: {duplicates}")
        return self


class LimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_s: float = 300.0
    output_limit_bytes: int = 32768

    @field_validator("timeout_s")
    @classmethod
    def _timeout_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_s must be positive")
        return value

    @field_validator("output_limit_bytes")
    @classmethod
    def _limit_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("output_limit_bytes must be positive")
        return value


class GitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: str = "working"
    base: str | None = None
    head: str | None = None

    @field_validator("selection")
    @classmethod
    def _known_selection(cls, value: str) -> str:
        if value not in SELECTIONS:
            raise ValueError(f"selection must be one of: {', '.join(SELECTIONS)}")
        return value


class ReportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = "json"
    destination: str | None = None
    redact: bool = True

    @field_validator("format")
    @classmethod
    def _known_format(cls, value: str) -> str:
        if value not in ("json", "markdown", "text"):
            raise ValueError("format must be one of: json, markdown, text")
        return value


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_files: int = 2000
    max_file_bytes: int = 1_048_576


class PatchProofConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)


def load_config(path: str | None) -> PatchProofConfig:
    """Load and validate a TOML configuration file.

    Returns default configuration when *path* is None. Raises ConfigError
    with a clean message for missing files, malformed TOML, and invalid
    values.
    """
    if path is None:
        return PatchProofConfig()
    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path!r}: {exc}") from exc
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path!r}: {exc}") from exc
    try:
        return PatchProofConfig.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        raise ConfigError(f"invalid configuration in {path!r}: {exc}") from exc
