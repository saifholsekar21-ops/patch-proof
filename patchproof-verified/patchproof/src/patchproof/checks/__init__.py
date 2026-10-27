"""Resolution of built-in check categories into executable CheckSpecs."""

from __future__ import annotations

import sys

from ..config import PatchProofConfig
from ..detect import ProjectFacts
from .base import CheckSpec

_PURPOSE_BY_CATEGORY = {
    "tests": "test",
    "lint": "lint",
    "typecheck": "typecheck",
    "deps": "deps",
}

_GENERIC_PYTHON = ("python", "python3")


def _resolve_command(command: list[str]) -> list[str]:
    """Run generic ``python``/``python3`` through the interpreter running
    PatchProof, so checks execute in the same environment as the CLI."""
    if command and command[0] in _GENERIC_PYTHON:
        return [sys.executable, *command[1:]]
    return command


def resolve_spec(
    category: str,
    config: PatchProofConfig,
    facts: ProjectFacts,
    root: str,
) -> CheckSpec | None:
    """Resolve a built-in category to a CheckSpec, or None when unresolvable.

    Precedence: explicit config override, then the first detected hint (even
    when its executable is unavailable, so the report shows a visible
    "executable not found" reason instead of silence).
    """
    override = getattr(config.checks, category).command
    if override is not None:
        return CheckSpec(
            id=category,
            category=category,
            tool=override[0],
            command=_resolve_command(override),
            required=category in config.checks.required,
            timeout_s=config.limits.timeout_s,
            cwd=root,
        )
    purpose = _PURPOSE_BY_CATEGORY[category]
    hints = facts.hints_for(purpose)
    if not hints:
        return None
    hint = hints[0]
    return CheckSpec(
        id=category,
        category=category,
        tool=hint.command[0],
        command=_resolve_command(hint.command),
        required=category in config.checks.required,
        timeout_s=config.limits.timeout_s,
        cwd=root,
    )


def build_check_specs(
    config: PatchProofConfig, facts: ProjectFacts, root: str
) -> list[CheckSpec]:
    """All external-check specs in deterministic order.

    Categories appear in the fixed order tests, lint, typecheck, deps
    (whether required or optional); custom checks follow in configuration
    order. The internal secrets category is handled by the engine.
    """
    specs: list[CheckSpec] = []
    configured = set(config.checks.required) | set(config.checks.optional)
    for category in ("tests", "lint", "typecheck", "deps"):
        if category not in configured:
            continue
        spec = resolve_spec(category, config, facts, root)
        if spec is not None:
            specs.append(spec)
    for custom in config.checks.custom:
        specs.append(
            CheckSpec(
                id=f"custom:{custom.name}",
                category="custom",
                tool=custom.command[0],
                command=_resolve_command(custom.command),
                required=custom.required,
                timeout_s=custom.timeout_s or config.limits.timeout_s,
                cwd=root,
            )
        )
    return specs
