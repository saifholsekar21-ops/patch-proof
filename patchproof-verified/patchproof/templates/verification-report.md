# PatchProof verification report

> Template for PHASE 8. Fill every section from the investigation journal.
> Every claim below must be backed by an entry in the JSON report; validate
> the JSON with `patchproof report report.json` (or
> `python scripts/validate_report.py`) before presenting this.

- Overall status: <!-- passed | failed | error | unverified -->
- Change selection: <!-- working | staged | unstaged | untracked | committed | all | none -->
- Repository revision: <!-- commit hash or "unknown" -->

## Problem and root cause

- Reported problem: <!-- symptom, how it was reported -->
- Root cause: <!-- demonstrated mechanism, with evidence ID F-xxx -->
- Confidence: <!-- demonstrated | strongly supported | hypothesis -->

## Files changed

| File | Change | Verification |
|------|--------|--------------|
| <!-- path --> | <!-- what changed --> | <!-- verified / unverified / proposed, by check id --> |

## Checks executed

| ID | Category | Required | Tool | Command | Status | Exit | Duration | Evidence |
|----|----------|----------|------|---------|--------|------|----------|----------|
| <!-- id --> | <!-- tests / lint / typecheck / secrets / deps / custom --> | <!-- yes/no --> | <!-- tool --> | <!-- exact command --> | <!-- passed / failed / skipped / error / unverified --> | <!-- int or - --> | <!-- s or - --> | <!-- captured output, quoted --> |

- Total: <!-- n --> run, <!-- n --> passed, <!-- n --> failed, <!-- n --> skipped,
  <!-- n --> error, <!-- n --> unverified.
- Optional checks never change the overall status; note any optional failures
  explicitly.

## Fixes implemented

- <!-- change, mapped to a finding id and the checks that verify it -->

## Remaining risks and unverified behavior

- <!-- every skipped/unverified check, every unverified change, every
     environment limitation, with the reason -->

## Follow-up actions

- <!-- next diagnostic step, missing coverage, or pending decision; leave
     empty only when nothing remains -->
