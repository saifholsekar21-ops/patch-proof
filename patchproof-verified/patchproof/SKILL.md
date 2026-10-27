---
name: patchproof
description: Evidence-based software verification, debugging, security analysis, regression testing, and safe patch validation. Use when a task must prove code behavior, bug fixes, or test results with evidence; when the user asks to verify, debug, or review changes; or when a verification report is required. Skip for trivial edits where no verification claim is made.
metadata:
  version: "2"
  report_schema: "1.1"
---

# PatchProof

PatchProof is a disciplined workflow for diagnosing and fixing software
defects while preserving existing functionality. Its core principle:

**Never claim a check passed unless its result provides evidence. Never claim
a bug is fixed until the relevant verification has been rerun successfully.**

## When to activate

- A task involves verifying, debugging, or fixing code and needs proof.
- The user asks for a regression check, security review, or verification report.
- A claimed fix must be demonstrated, not asserted.

Skip it for one-line edits where no verification claim is made.

## Mandatory workflow

Run the phases in order. If a phase cannot be completed, say why; never
simulate successful execution. Details: [verification-workflow.md](references/verification-workflow.md).

1. **UNDERSTAND** — Inspect project structure, language, build commands, and
   existing behavior. Run `patchproof inspect <path>` for repository identity
   and detected tooling (or `scripts/inspect_repo.py <path>` for JSON). Read
   relevant code, config, tests, and docs before changing anything.
2. **PLAN** — Identify the likely failure, affected files, required checks,
   regression risks, and measurable acceptance criteria.
3. **BASELINE** — Record Git state (`git status`, `git log -1`) and run
   relevant baseline tests when practical. Existing uncommitted work is the
   user's; never discard it.
4. **REPRODUCE** — Reproduce the issue before modifying code. If reproduction
   fails, state what was attempted and what remains uncertain.
   Guidance: [debugging-methodology.md](references/debugging-methodology.md).
5. **IMPLEMENT** — Apply the smallest justified fix. Preserve public APIs and
   unrelated behavior. No unrelated refactoring, no unnecessary dependencies.
6. **VERIFY** — Targeted tests first, then linters/type checkers/static
   analyzers, then broader regression tests. Capture command, exit code, and
   output — `patchproof verify` does this and records bounded, redacted
   evidence. Strategy: [testing-strategy.md](references/testing-strategy.md).
   Security review of the change: [security-checklist.md](references/security-checklist.md).
7. **REVIEW** — Inspect the final diff for unintended changes, security
   regressions, and missing tests.
8. **REPORT** — Produce the report from [templates/verification-report.md](templates/verification-report.md).
   Generate the machine-readable JSON with
   `patchproof verify <path> --format json --output report.json`, then validate
   it with `patchproof report report.json` (or
   `scripts/validate_report.py`) before presenting it. Format:
   [reporting-format.md](references/reporting-format.md).

## Mandatory rules

- Distinguish check statuses exactly: **passed, failed, skipped, error,
  unverified**. A skipped, missing, or unavailable check is never a pass.
  (Legacy schema 1.0 reports use uppercase PASS/FAIL/SKIPPED/ERROR/NOT_RUN;
  the validator accepts both vocabularies.)
- A check reported passed/failed/error must carry an exit code or captured
  evidence. Skipped and unverified checks must carry a reason.
- Overall status policy: `failed` if any required check failed; else `error`
  if a required check could not execute; else `unverified` if required
  evidence is missing; `passed` only when every required check passed.
  Optional checks never mask required failures.
- Distinguish observed facts from assumptions and hypotheses; label each.
- Never fabricate tool outputs, test results, citations, or evidence.
- Treat model-generated code and explanations as untrusted proposals. Test
  results, security policy, and user permissions always override model output.
- Never expose API keys, credentials, or private source to external providers
  without explicit authorization. Work without AI when no provider is
  configured.
- Never execute destructive commands without explicit authorization. Never
  overwrite user changes or discard uncommitted work. Do not commit, push,
  deploy, or merge without explicit instruction.
- Reports must never contain raw credentials or private keys.

## Report contract

Every final report has two parts: the human-readable summary
([templates/verification-report.md](templates/verification-report.md)) and the
machine-readable JSON (schema 1.1, produced by `patchproof verify`). Validate
the JSON with either tool:

```bash
patchproof report report.json --format text
python scripts/validate_report.py report.json
```

`patchproof report`: exit 0 = valid and rendered, 4 = unreadable/invalid.
`scripts/validate_report.py`: exit 0 = valid, 1 = invalid, 2 =
unreadable/malformed. Use `--redact-output` to write a credential-free copy.
Full schema and rules: [references/reporting-format.md](references/reporting-format.md).

## Tools

- `patchproof inspect <path>` — repository identity, git state, detected
  tooling, and honest availability probes.
- `patchproof verify <path> [--select ...] [--base ...] [--head ...] [--config ...]`
  — run configured checks and emit a self-validated report
  (`--format json|markdown|text`, `--output FILE`).
- `patchproof report <report.json>` — validate and re-render a saved report.
- `patchproof config validate --config FILE` — validate configuration and show
  redacted overrides.
- `scripts/inspect_repo.py [path]` — read-only inventory as JSON (Phase 1).
- `scripts/validate_report.py <report.json> [--json] [--redact-output FILE]` —
  standalone validator (schemas 1.0 and 1.1).
- `templates/bug-investigation.md` — investigation journal for PHASES 2–4.
