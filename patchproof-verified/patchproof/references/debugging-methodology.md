# PatchProof debugging methodology

Goal: find the most likely root cause using available evidence, with the
smallest possible change — not by rewriting code until something passes.

## 1. Reproduce first

- Re-run the failing test or the reported repro steps. Capture the exit code
  and the full traceback/log output; this is evidence, not decoration.
- Note whether the failure is deterministic. A flaky failure changes the
  diagnosis path entirely (see below).
- If you cannot reproduce: say so explicitly. List what was attempted and on
  what environment. You may proceed to static analysis, but the conclusion is
  a hypothesis with `unverified` status, not a fix.

## 2. Read the failure, don't pattern-match it

Work through the traceback from the bottom up:

- The last frame is where the error was raised; the frames above show how the
  program got there.
- Distinguish cause from symptom. A `KeyError` in a caller is often the
  symptom of a wrong return value or a missing write earlier in the flow.
- Check the actual values involved. Instrument or log only if needed, and
  remove instrumentation before reporting the fix.

## 3. Form hypotheses and rank them

For each candidate cause, write down:

- What evidence supports it (observed output, code path, history).
- What evidence would disprove it.
- The smallest experiment or test that distinguishes it from the others.

Rank by how well each explains *all* the observed facts. Prefer the
hypothesis that explains the failure with the fewest extra assumptions, but
verify it instead of trusting the ranking.

## 4. Verify the root cause before fixing

- Prove the mechanism: e.g. show that the bad value is actually produced at
  the suspected line (a targeted test, a minimal repro, or a temporary
  assertion), not merely that a fix at that line makes the test pass.
- A fix that makes tests pass is weaker evidence than a demonstrated
  mechanism. Record which one you have.

## 5. Minimal fix, no collateral damage

- Change only what the demonstrated mechanism requires.
- If a second bug is discovered while diagnosing, note it as a separate
  finding and fix it separately (or leave it and report it). Do not bundle it
  silently into the main fix.
- Avoid speculative rewrites of adjacent code "while we're here".

## 6. Flaky and environmental failures

- If the failure does not reproduce consistently, say so. Run the test N
  times (record N) and report the pass/fail counts honestly.
- Distinguish test bugs from product bugs: a test that fails only in CI or
  only on one OS is a finding of its own.
- Timeouts: record the duration and the configured timeout. A timed-out check
  is ERROR with the duration as evidence, never PASS.

## 7. When evidence runs out

Stop and report instead of guessing:

- State the strongest hypothesis, the evidence for and against it, and what
  remains unknown.
- Propose the next diagnostic step (a log line, a bisect, a minimal repro
  script) as a follow-up action.
- Do not ship a change whose verification status you cannot demonstrate; mark
  it `proposed`.
