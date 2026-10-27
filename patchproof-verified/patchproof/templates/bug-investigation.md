# Bug investigation journal

> Template for PHASES 2–4. This is working notes, not the final report.
> Facts and hypotheses stay separate all the way through.

## Task

- Task ID: <!-- PP-yyyymmdd-nnn -->
- Reported problem: <!-- exact symptom or test name -->
- Desired behavior: <!-- what should happen instead -->
- Repository state: <!-- branch, HEAD revision, pre-existing dirty files -->

## Reproduction

- Steps attempted: <!-- exact commands, inputs, environment -->
- Outcome: <!-- captured output, exit code, traceback excerpt -->
- Reproduced? <!-- yes / no / intermittently (N runs, M failures) -->

## Evidence log

| # | Observation (fact) | Source (command/output/test) |
|---|--------------------|------------------------------|
| 1 | <!-- -->           | <!-- -->                     |

## Hypotheses

| # | Hypothesis | Evidence for | Evidence against | Test to decide |
|---|------------|--------------|------------------|----------------|
| 1 | <!-- -->   | <!-- -->     | <!-- -->         | <!-- -->       |

## Root cause conclusion

- Selected hypothesis: <!-- which, and why it wins -->
- Demonstrated mechanism: <!-- how the bad value/state is actually produced -->
- Remaining uncertainty: <!-- what is still unknown, or "none" -->

## Fix plan

- Smallest change: <!-- file(s) and description -->
- Behavior preserved: <!-- public APIs and existing semantics kept -->
- Checks to run after the fix: <!-- targeted, static, regression -->
- Acceptance criteria: <!-- measurable -->

## Notes

- <!-- assumptions, blocked steps, follow-up ideas -->
