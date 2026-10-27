# PatchProof report format (schema 1.1)

The machine-readable verification report is a single JSON object. PatchProof
self-validates every generated report, and both validators enforce the same
contract:

```bash
patchproof report report.json          # exit 0 valid, 4 unreadable/invalid
python scripts/validate_report.py report.json   # exit 0 valid, 1 invalid, 2 unreadable
```

Neither validator echoes detected secret values; reports containing secret
material are rejected with code `secret_material`. Schema 1.0 reports remain
accepted by the validator and can be rendered by `patchproof report`.

## Top-level fields

| Field              | Type   | Required | Notes                                                       |
|--------------------|--------|----------|-------------------------------------------------------------|
| schema_version     | string | yes      | `"1.1"` (validator also accepts `"1.0"`)                    |
| patchproof_version | string | yes      | version of the tool that produced the report                |
| task_id            | string | yes      | stable identifier for the task                              |
| task_description   | string | yes      | one-line summary of the task                                |
| generated_at       | string | yes      | ISO-8601 timestamp                                          |
| repository         | object | yes      | see below                                                   |
| selection_policy   | string | yes      | `working` \| `staged` \| `unstaged` \| `untracked` \| `committed` \| `all` \| `none` |
| changed_files      | array  | no       | examined files and their diff metadata (see below)          |
| findings           | array  | yes      | may be empty (`[]` when there are none)                     |
| checks             | array  | yes      | may be empty                                                |
| skipped_checks     | array  | no       | legacy view; CLI reports derive the skipped section from `checks` |
| execution_errors   | array  | no       | internal failures that prevented a check from running       |
| overall_status     | string | yes      | `passed` \| `failed` \| `error` \| `unverified`              |
| limitations        | array  | no       | strings describing unverified behavior                      |
| conclusion         | string | no       | human summary                                               |
| changes            | array  | no       | schema 1.0 compatibility; CLI reports emit `[]`             |

Unknown top-level fields produce warnings, not errors.

## repository

| Field    | Type    | Notes                                             |
|----------|---------|---------------------------------------------------|
| path     | string  | required, non-empty                               |
| revision | string  | optional; commit hash when known                  |
| branch   | string  | optional; null when detached or not a repository  |
| dirty    | boolean | optional; whether the tree had changes            |
| detached | boolean | optional; true when HEAD is detached              |

## changed_files

One entry per examined file. Untracked files are listed with status `U`; they
have no diff and are never claimed to be part of one.

| Field     | Type    | Required | Notes                                              |
|-----------|---------|----------|----------------------------------------------------|
| path      | string  | yes      | repository-relative path                           |
| status    | string  | no       | porcelain/diff letter: `A`, `M`, `D`, `R`, `C`, `T`, `U` |
| origin    | string  | no       | `staged`, `unstaged`, `untracked`, `committed <base>..<head>` |
| old_path  | string  | no       | source path for renames/copies (committed ranges)  |
| additions | integer | no       | non-negative; diffstat for committed ranges        |
| deletions | integer | no       | non-negative; diffstat for committed ranges        |

## checks

One entry per verification step. Status is exact and lowercase:

`passed` | `failed` | `skipped` | `error` | `unverified`

| Field      | Type    | Required | Notes                                                       |
|------------|---------|----------|-------------------------------------------------------------|
| id         | string  | yes      | unique (`custom:<name>` for custom checks)                  |
| tool       | string  | yes      | tool identity, e.g. `pytest`, `ruff`, `patchproof-secrets`  |
| category   | string  | yes      | `tests` \| `lint` \| `typecheck` \| `secrets` \| `deps` \| `custom` |
| command    | string  | yes      | exact command line, re-runnable (`(not configured)` when unresolved) |
| status     | string  | yes      | one of the five values above                                |
| required   | boolean | no       | defaults to true; drives the overall policy                 |
| exit_code  | integer | no       | required-or-evidence for passed/failed/error                |
| duration_s | number  | no       | non-negative                                                |
| summary    | string  | no       | one-line human summary                                      |
| evidence   | array   | no       | strings of captured, redacted output                        |
| reason     | string  | no       | **required** for skipped and unverified; explains error too |

Evidence rule: a check with status passed/failed/error must provide a non-null
`exit_code` or at least one non-empty `evidence` string. A check that never
executed (missing tool, timeout) reports its reason as evidence. A skipped or
unverified check must provide a non-empty `reason`.

## Overall status policy

- `failed` — any required check failed.
- `error` — else, any required check could not execute reliably.
- `unverified` — else, a required check is unverified or skipped, or no
  required checks were configured.
- `passed` — only when every required check passed.

Optional checks are reported but never override a required failure.

## findings

One entry per defect, risk, or observation.

| Field       | Type   | Required | Notes                                              |
|-------------|--------|----------|----------------------------------------------------|
| id          | string | yes      | assigned by the renderer (`F-001`, ...)            |
| severity    | string | yes      | `critical` \| `high` \| `medium` \| `low` \| `info` |
| status      | string | no       | `open` (default) \| `fixed` \| `wontfix` \| `duplicate` |
| title       | string | yes      |                                                    |
| description | string | yes      |                                                    |
| evidence    | array  | yes      | non-empty list of strings (observed output, lines) |
| locations   | array  | no       | objects with `file` (required), optional `line`/`column` |

## skipped_checks and execution_errors

`skipped_checks` is `[{id, reason}]` for legacy compatibility. CLI reports keep
skipped/unverified checks in `checks` (with status and reason) and emit an
empty array here; renderers merge the two views without duplication.

`execution_errors` is `[{check_id, message}]` for internal failures that
prevented a check from starting; the corresponding check still appears with
status `error`.

## Secret policy

Reports must never contain raw credentials, private keys, tokens, or
passwords. Captured output is redacted before it is stored, and the validator
detects AWS access keys, AWS-style secret keys, GitHub fine-grained and classic
tokens, Slack and Stripe keys, Google API keys, JWTs, private key blocks,
bearer tokens, and `key=value` credential assignments. A report containing a
match is rejected with code `secret_material`. To sanitize an older report:

```bash
python scripts/validate_report.py report.json --redact-output clean.json
```

Detection and redaction are pattern-based; see `SECURITY.md` for limitations.

## Minimal valid example (schema 1.1)

```json
{
  "schema_version": "1.1",
  "patchproof_version": "1.1.0",
  "task_id": "PP-001",
  "task_description": "Demonstrate the report format",
  "generated_at": "2026-10-26T00:00:00+00:00",
  "repository": {"path": ".", "revision": null, "branch": null, "dirty": false},
  "selection_policy": "working",
  "changed_files": [],
  "findings": [],
  "checks": [
    {
      "id": "tests",
      "tool": "pytest",
      "category": "tests",
      "command": "python -m pytest -q",
      "status": "passed",
      "required": true,
      "exit_code": 0,
      "evidence": ["2 passed in 0.31s"]
    }
  ],
  "skipped_checks": [],
  "execution_errors": [],
  "overall_status": "passed",
  "limitations": [],
  "conclusion": ""
}
```

## Schema 1.0 compatibility

The original contract used `schema_version: "1.0"`, uppercase check statuses
(`PASS`, `FAIL`, `SKIPPED`, `ERROR`, `NOT_RUN`), a `changes` array with
`verification_status`/`verified_by`, and no `overall_status`. The validator
enforces the 1.0 rules when `schema_version` is `"1.0"` and the 1.1 rules
otherwise. `patchproof report` normalizes 1.0 documents for rendering and
derives an overall status from the checks; it does not modify the source file.
