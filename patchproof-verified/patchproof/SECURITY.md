# Security policy

PatchProof is a local verification tool. It runs checks you configure, reads
your repository, and writes reports. This document states what it protects
against, what it does not, and how to report a vulnerability.

## Supported versions

Security fixes are applied to the latest release line (currently `1.1.x`).

## Reporting a vulnerability

Please report vulnerabilities privately through your repository host's
security-advisory feature (for example, "Report a vulnerability" on GitHub)
rather than a public issue. Include the version, a minimal reproduction, and
the impact you observed. Please do not include live credentials in the report;
rotate anything exposed before sharing logs.

## Safety properties implemented and tested

| Property | Implementation |
|----------|----------------|
| Read-only git access | Only the `rev-parse`, `status`, and `diff` subcommands are invoked, as argv arrays. No stage/commit/checkout/reset code path exists. `GIT_OPTIONAL_LOCKS=0` prevents optional index refreshes, `core.fsmonitor` is disabled, and diffs use `--no-ext-diff --no-textconv` so repository-configured helper programs do not run. Revision arguments beginning with `-` are rejected so they cannot be parsed as git options. Read-only behavior is covered by `tests/test_readonly.py` and `tests/test_repo_git.py`. |
| No shell interpretation | Every process is started with an argument array (`shell=False`). Configuration commands are TOML arrays, never command strings. |
| No AI-generated commands | Check commands come only from detection hints or explicit user configuration. PatchProof never generates or executes commands produced by a model. |
| No automatic installs | Detection probes `--version` only. `npx` is probed as a runner and is never allowed to download packages. PatchProof never installs dependencies during verification. |
| Bounded execution | Per-check timeout (default 300 s), terminate-then-kill escalation, output drained to temporary files, per-stream cap on retained/reported bytes. |
| Output redaction | Captured stdout/stderr and JSON reports are scrubbed for known credential patterns before storage. The report validator rejects documents containing secret material (`secret_material`). |
| Stable exit codes | Documented 0–4 codes; usage errors are never conflated with verification results. |
| Report self-validation | Every generated report is validated against schema 1.1 before it is returned. |

## Explicit non-goals

- **No sandboxing.** Checks execute as subprocesses with the invoking user's
  privileges and full filesystem/network access. A malicious custom check or a
  compromised test dependency is outside PatchProof's control. Run untrusted
  projects in a container or VM.
- **No network isolation.** Checked tools may access the network.
- **No protection from resource exhaustion inside a check** beyond the timeout
  and the cap on retained output. A check can still write unbounded data to
  its temporary output spill files (consuming disk) or exhaust other resources
  until it is terminated.
- **No filesystem write protection for executed checks.** A check may create
  artifacts in the working tree, such as `__pycache__/` or `.pytest_cache/`.
  PatchProof's own git operations never modify tracked files, the index, or
  history; only the checks it launches can write files.
- **No guarantee that a clean secret scan means no secret exists.** See below.

## Secret detection: coverage and limitations

Detection is a set of regular expressions. It is a defensive aid, not a
guarantee.

Detected patterns:

- AWS access key IDs (`AKIA...`) and 40-character AWS-style secret keys (the
  heuristic requires at least one non-hex character so git SHAs are not
  flagged)
- GitHub tokens: classic (`ghp_`/`gho_`/`ghu_`/`ghs_`), fine-grained
  (`github_pat_`), and `ghx_`
- Slack tokens (`xox[baprs]-...`)
- Stripe live keys (`sk_live_`/`rk_live_`)
- Google API keys (`AIza...`)
- JSON Web Tokens (`eyJ...eyJ...`)
- PEM private-key blocks
- `Bearer` authorization tokens
- Generic assignments such as `password=...`, `api_key: ...`, `secret=...`,
  `token=...` (values of 8+ characters, with a short denylist of placeholder
  values such as `changeme` and `redacted`)

Known limitations:

- Obfuscated, split, encoded, or novel credential formats are not detected.
- Short or low-entropy secrets are intentionally not matched to limit false
  positives.
- Only the first 8 KiB of each file is scanned; files larger than
  `max_file_bytes` (default 1 MiB) are skipped entirely.
- Vendored directories (`node_modules`, `vendor`, virtualenvs, build output,
  `.git`), lock files, and binary files are skipped.
- At most `max_files` (default 2000) files are scanned per run.
- Git history is not scanned — only files currently present in the tree.
- PowerShell/gh CLI style credentials (`ghp_` etc.) are matched only with the
  documented prefixes and lengths.

Redaction uses the same patterns, so a secret the scanner does not recognize
is also not redacted. Never paste raw logs containing credentials into a
report; rotate anything exposed.

## Report contents

Reports contain command lines, exit codes, timings, and bounded, redacted
output excerpts. They do not contain environment variables, file contents
beyond matched-output excerpts, or configured secrets (the `config validate`
output redacts override commands before printing).
