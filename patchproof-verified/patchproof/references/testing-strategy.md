# PatchProof testing strategy

## Status vocabulary (exact)

| Status    | Meaning                                                      | Required fields          |
|-----------|--------------------------------------------------------------|--------------------------|
| PASS      | Ran, succeeded, evidence captured                            | exit_code or evidence    |
| FAIL      | Ran, failed (assertion or product failure)                   | exit_code or evidence    |
| ERROR     | Ran, crashed for environmental/infra reasons                 | exit_code or evidence    |
| SKIPPED   | Deliberately not run; known reason (e.g. tool missing)       | reason                   |
| NOT_RUN   | Not yet run; reason recorded                                 | reason                   |

A SKIPPED or NOT_RUN check is never evidence of success. A FAIL is never
reported as PASS, and an ERROR is never reported as FAIL without saying why.

## Order of execution

1. **Targeted tests first** — the tests that cover the changed behavior.
2. **Static checks** — linter, type checker, formatter check-mode. Fast, wide,
   and they catch mechanical regressions.
3. **Security review** — the checklist, plus any available security tooling.
4. **Broader regression** — the full unit suite, then integration/E2E when
   the change touches shared code or public APIs.

Stop expanding only when the change's blast radius is covered. A one-line
format change does not need the E2E suite; a change to a shared serializer
does.

## What counts as evidence

For every executed check, capture:

- the exact command line (so it can be re-run);
- the exit code;
- a few lines of actual output (the summary line, the failure list, the
  traceback header) — enough to distinguish "ran and passed" from "ran";
- duration when available.

Do not paraphrase output as evidence. Copy it.

## Finding the right tests

- Use `scripts/inspect_repo.py` to locate test files and suggested commands,
  then verify the command exists (`<runner> --version`) before running it.
- Name the tests you ran in the report. "Ran the test suite" without a
  command is not a check; it is a sentence.
- If the repository has no tests for the changed code, say so under
  `limitations` and mark the change `unverified` or `proposed`.

## Flaky tests and timeouts

- A test that fails intermittently: run it N times, report the counts, and
  treat the underlying instability as a separate finding.
- A timed-out check is ERROR with the timeout duration recorded.

## Missing tools

- A missing tool (no pytest, no eslint, no npm) turns its check into SKIPPED
  with the reason "tool not installed in this environment" — never into an
  assumption that it would have passed.
- Do not install heavy toolchains without user authorization. Prefer what is
  already available.

## Regression safety

- Before the fix, note which tests passed at baseline (PHASE 3). After the
  fix, the same set must still pass. New failures that appear after the fix
  are regressions until proven otherwise.
- A fix is only `verified` when a check that exercises the fixed behavior
  passes **after** the change. A passing check from before the change does
  not verify the fix.
