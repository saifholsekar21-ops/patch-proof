# PatchProof verification workflow

The eight phases below apply to every task that makes verification claims.
If a phase cannot be completed, record why and continue; a blocked phase is a
finding, not a failure to hide.

## PHASE 1 — UNDERSTAND

Goal: know the system before touching it.

1. Run `python scripts/inspect_repo.py <path>` (read-only). It reports OS and
   runtime facts, git state, detected languages/frameworks, and suggested
   commands. Treat the suggested commands as hypotheses to confirm, not facts.
2. Read the files that matter: entry points, the changed module, its tests,
   and its configuration. Skip this only for trivial tasks.
3. Check `git status` and `git log -1 --oneline` yourself. The inventory
   script is a snapshot; the shell is authoritative.
4. Identify existing behavior that must remain unchanged: public APIs,
   documented semantics, and tests that encode them.

Output: a short list of components, build/test commands (verified to exist),
and protected behavior.

## PHASE 2 — PLAN

Write down, before editing:

- The most likely failure hypothesis and the evidence that would support it.
- Affected files and their dependents (who calls the changed code).
- The checks that will be run (targeted tests, lint, type check, security
  scan, build, broader regression) and what each must show.
- Measurable acceptance criteria (e.g. "the failing test passes and the other
  14 tests stay green", not "it works").
- Regression risks: what could silently break.

Use [templates/bug-investigation.md](../../templates/bug-investigation.md) as
the journal for this phase and the next two.

## PHASE 3 — BASELINE

Goal: know the starting state, so later results are comparable.

1. Record git state: current branch, HEAD revision, and whether the working
   tree was dirty before you started. Uncommitted changes belong to the user;
   never stash, reset, or discard them without explicit instruction.
2. Run the relevant baseline tests when practical. If the suite is already
   red, record exactly which tests fail — those failures predate your change.
3. If baseline tests cannot run (missing deps, broken environment), record
   that as a limitation. A test you could not run is NOT_RUN, not PASS.

## PHASE 4 — REPRODUCE

Goal: observe the reported problem before fixing it.

1. Re-run the failing test or reproduce the reported error with the minimal
   steps available.
2. Capture the actual output: exit code, traceback, log lines. This captured
   output becomes evidence for the FAIL check in the report.
3. If reproduction fails: state what was attempted, on what environment, and
   what remains uncertain. You may still propose a fix, but its verification
   status must be `unverified` or `proposed`, never `verified`.

See [debugging-methodology.md](debugging-methodology.md) for how to turn the
reproduction into a root cause.

## PHASE 5 — IMPLEMENT

1. Apply the smallest change that addresses the demonstrated problem.
2. Preserve public APIs and existing behavior unless the task explicitly
   requires changing them. Do not refactor adjacent code, reformat unrelated
   lines, or add dependencies as a side effect.
3. Edit incrementally and re-read the diff of every edit.

## PHASE 6 — VERIFY

Run checks in this order; each becomes an entry in the report's `checks`
array with its command, exit code, and captured output:

1. **Targeted tests** for the changed behavior.
2. **Static checks**: linters, type checkers, formatters-in-check-mode.
3. **Security review** of the changed code paths (see
   [security-checklist.md](security-checklist.md)).
4. **Broader regression tests** when the change touches shared code.

Record for every check: the exact command, exit code, duration when known,
and a few lines of captured output. If a tool is missing, record the check as
SKIPPED with the reason. If a check fails for environmental reasons, record
ERROR, not FAIL, and say why.

## PHASE 7 — REVIEW

1. Read the complete final diff. Look for unintended changes, debug prints,
   commented-out code, and files touched by accident.
2. Ask: does any change introduce a security regression (see the checklist)?
3. Ask: is the fix covered by a test that would fail if the bug returned?
   If not, say so under `limitations`.
4. Confirm the working tree still contains the user's pre-existing changes.

## PHASE 8 — REPORT

1. Fill [templates/verification-report.md](../../templates/verification-report.md)
   from the journal.
2. Emit the JSON report per [reporting-format.md](reporting-format.md).
3. Validate: `python scripts/validate_report.py report.json`. Fix any errors
   (they usually mean an unverifiable claim or a missing piece of evidence).
4. Present the human-readable report with the validation outcome.

## Rules that override everything

- Never interpret SKIPPED or NOT_RUN as PASS.
- Never mark a change `verified` without a PASSing check listed in
  `verified_by`.
- Never fabricate output. If you did not run it, you did not run it.
- Destructive commands (deletes, force operations, resets) require explicit
  user authorization. Commits, pushes, and deploys are never automatic.
