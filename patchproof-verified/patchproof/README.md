# PatchProof

**Evidence-based code verification for local repositories.**

PatchProof is a command-line tool that inspects a repository, runs configured
verification checks (tests, lint, type checking, dependency audit, secret
scanning, custom commands), and produces a machine-validated report that
distinguishes *passed*, *failed*, *skipped*, *error*, and *unverified* evidence.

> Never claim a check passed unless its result provides evidence. Never claim a
> fix is verified until the relevant check was rerun successfully.

PatchProof also ships as an agent skill (`SKILL.md`) for disciplined
verification workflows — see [Using PatchProof as a skill](#using-patchproof-as-a-skill).

## Requirements

- Python 3.11+
- Git on `PATH` for repository analysis (verification can run without git via
  `--select none`)

## Install

From a checkout of this repository:

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on POSIX
pip install -e ".[dev]"       # runtime + test/lint/type-check tooling
```

The console script is `patchproof`:

```bash
patchproof --version
patchproof --help
```

## Quick start

```bash
# 1. Inspect repository identity, git state, and detected tooling
patchproof inspect .

# 2. Verify the working tree (staged + unstaged + untracked changes)
patchproof verify .

# 3. Verify a committed range
patchproof verify . --select committed --base origin/main --head HEAD

# 4. Verify without change analysis (whole repository)
patchproof verify . --select none

# 5. Re-render a saved report (validates it first)
patchproof verify . --format json --output report.json
patchproof report report.json --format markdown

# 6. Validate a configuration file before using it
patchproof config validate --config patchproof.toml
```

A runnable example lives in
[`examples/demo-project`](examples/demo-project):

```bash
patchproof verify examples/demo-project --select none \
  --config examples/demo-project/patchproof.toml
```

Example outputs: [`examples/sample-report.json`](examples/sample-report.json)
and [`examples/sample-report.md`](examples/sample-report.md). A fully commented
configuration is in
[`examples/patchproof.example.toml`](examples/patchproof.example.toml).

## Exit codes

`verify` exits with a stable code derived from the overall status:

| Code | Meaning |
|------|---------|
| 0 | `passed` — every required check passed |
| 1 | `failed` — a required check failed; also: invalid configuration |
| 2 | `error` — a required check could not execute reliably |
| 3 | `unverified` — required evidence is missing (no check configured, skipped, or unverified) |
| 4 | usage, input, or git-selection error (bad option, missing path, invalid revision) |

`inspect` and `report` exit 0 on success and 4 on input errors.
`config validate` exits 0 when valid, 1 when invalid, 4 on usage errors.

## What verify does

1. **Detects** languages and candidate tooling from configuration files
   (`pyproject.toml`, `package.json`, `tsconfig.json`, ...). Detection only
   *proposes* commands; availability is probed with `--version` — project
   scripts are never executed for detection, and `npx` is never asked to
   auto-install anything.
2. **Selects changes** (see below) using read-only git commands.
3. **Runs checks** in a fixed order — `tests`, `lint`, `typecheck`, `secrets`,
   `deps`, then custom checks in configuration order — with per-check timeouts,
   bounded output, and forced termination on timeout.
4. **Aggregates results** under a required/optional policy and **self-validates**
   the report against schema 1.1 before returning it.

If PatchProof cannot determine a change set (for example `--select committed`
without revisions), it stops with a usage error rather than guessing.

### Change selection

| Selection | Files examined |
|-----------|----------------|
| `working` (default) | staged + unstaged + untracked |
| `staged` | index vs. `HEAD` |
| `unstaged` | worktree vs. index |
| `untracked` | files git does not track yet |
| `committed` | `--base`..`--head` diff metadata (both required) |
| `all` | working-tree categories plus the committed range |
| `none` | no change analysis (whole-repository verification) |

Untracked files have no diff. PatchProof lists them separately and records a
limitation note; it never claims they were part of a diff. Renames and status
letters (`A`, `M`, `D`, `R`, ...) come from `git status --porcelain` and
`git diff --name-status`.

### Check categories

| Category | Default policy | How the command is chosen |
|----------|----------------|---------------------------|
| `tests` | required | explicit `[checks.tests]` override, else the first detected hint |
| `lint` | optional | same |
| `typecheck` | optional | same |
| `secrets` | required | built-in read-only regex scan |
| `deps` | optional | same as `tests` |
| `custom` | per-entry `required` flag | explicit `[[checks.custom]]` entries only |

Missing executables are **never** treated as passes: a missing required tool is
`error`, a missing optional tool is `skipped`, and both carry a reason. Generic
`python`/`python3` commands are executed with the same interpreter running
PatchProof, so checks run in the environment you installed it into.

## Configuration

TOML, loaded with `--config path.toml` (safe defaults apply without a file).
See [`examples/patchproof.example.toml`](examples/patchproof.example.toml) for
every key.

```toml
[checks]
required = ["tests", "secrets"]
optional = ["lint", "typecheck", "deps"]

[checks.tests]
command = ["python", "-m", "pytest", "-q"]

[[checks.custom]]
name = "migration-dry-run"
command = ["python", "manage.py", "migrate", "--check"]
required = true
timeout_s = 120

[limits]
timeout_s = 300
output_limit_bytes = 32768

[git]
selection = "working"        # working | staged | unstaged | untracked | committed | all | none
# base = "origin/main"       # required for committed/all
# head = "HEAD"

[report]
format = "json"              # json | markdown | text
destination = "report.json"  # optional; --output wins
redact = true                # mask credential patterns in JSON output

[secrets]
enabled = true
max_files = 2000
max_file_bytes = 1048576
```

Rules enforced by the loader: unknown keys, unknown categories, duplicate
categories, overlapping required/optional entries, empty argv arrays, invalid
selection/format values, and non-positive timeouts are rejected with a clear
error. Commands are argument arrays — there is no shell interpretation and
never will be.

## Reports

Every run produces a schema-1.1 report:

- **JSON** — machine-readable, validated against the contract before it is
  emitted (self-validation), and re-validated by `patchproof report`.
- **Markdown** — human-readable summary with per-check evidence and limitations.
- **Text** — one line per check for terminals.

Overall status policy: `failed` if any required check failed; else `error` if a
required check could not execute; else `unverified` if required evidence is
missing or no required checks are configured; `passed` only when all required
checks passed. Optional checks are reported but never override a required
failure.

`schema 1.0` reports (from earlier versions and `scripts/validate_report.py`)
remain readable: `patchproof report` validates and renders them, and the
existing validator is the single report-validation implementation.

## Security and limitations

- **Read-only:** git access uses argument arrays and read-only commands only.
  Verification does not modify tracked files, stage, commit, or rewrite
  history. Custom checks are arbitrary programs and can do whatever the
  invoking user can — PatchProof does not sandbox them.
- **No shell:** all checks run as argv arrays (`shell=False`); no AI-generated
  command is ever executed.
- **Bounded execution:** per-check timeout with terminate-then-kill, output
  capped per stream, captured to temp files so a chatty check cannot exhaust
  memory.
- **Redaction:** captured output and JSON reports are scrubbed for known
  credential patterns before storage. Redaction is pattern-based and cannot
  cover every secret format.
- **Secret scanning is heuristic:** a regex candidate, not proof of a live
  secret. It scans the first 8 KiB of each text file, skips vendored/binary
  files, and does not inspect git history.

Full threat model and regex coverage: [SECURITY.md](SECURITY.md).

## Using PatchProof as a skill

`SKILL.md` defines an agent workflow (UNDERSTAND → PLAN → BASELINE →
REPRODUCE → IMPLEMENT → VERIFY → REVIEW → REPORT) built on the same evidence
rules. The Phase-1 helpers remain available:

- `scripts/inspect_repo.py [path]` — read-only inventory as JSON.
- `scripts/validate_report.py <report.json>` — standalone report validator
  (schema 1.0 and 1.1; exit 0 valid, 1 invalid, 2 unreadable).
- `references/` — workflow, debugging, security, testing, and report guidance.
- `templates/` — human report and investigation templates.

## Development

```bash
python -m pytest tests -q     # 195 tests; temp dirs only, no network
ruff check .
mypy src
python -m build              # packaging check
```

See [CONTRIBUTING.md](CONTRIBUTING.md). CI runs the suite on Python 3.11–3.13
across Ubuntu and Windows.

## License

MIT — see [LICENSE](LICENSE).
