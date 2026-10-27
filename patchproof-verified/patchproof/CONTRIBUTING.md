# Contributing to PatchProof

Thanks for helping improve PatchProof. This project values evidence over
assertion: changes should come with tests, and reports should be reproducible.

## Development setup

```bash
python -m venv .venv
.venv/Scripts/activate        # POSIX: source .venv/bin/activate
pip install -e ".[dev]"
```

## Before opening a pull request

Run all three gates locally:

```bash
python -m pytest tests -q
ruff check .
mypy src
```

The test suite must pass on Python 3.11, 3.12, and 3.13 (CI runs all three on
Ubuntu and Windows). Tests use temporary directories only and must not require
network access.

## Guidelines

- **Test behavior, not implementation details.** New checks, config rules,
  git selections, and CLI exit codes need tests that fail without the change.
- **Never fabricate evidence in fixtures.** Test data that looks like a
  credential must be an obviously fake example and is never a live value.
- **Keep commands as argv arrays.** `shell=True`, string commands, and
  `os.system` are not acceptable anywhere in the verification path.
- **Respect the read-only guarantee.** Verification must not stage, commit,
  modify tracked files, or rewrite history. `tests/test_readonly.py` guards
  this; extend it if you touch git handling.
- **Schema changes require validator changes.** If you change the report
  shape, update `src/patchproof/validate.py`, `scripts/validate_report.py`,
  `references/reporting-format.md`, and the tests together. Reports must remain
  self-validating.
- **Statuses are exact.** `skipped` is never a pass, missing tools are never a
  pass, and optional checks never mask required failures.
- **Document limitations honestly.** If something is heuristic or unsupported,
  say so in `SECURITY.md` or the README rather than implying a guarantee.
- **Keep the diff focused.** No unrelated refactoring, no new runtime
  dependencies without justification, no decorative files.

## Commit style

Short imperative subject lines (for example, `Fix staged-file status letters`);
use the body to explain *why* when it is not obvious.

## Reporting bugs and vulnerabilities

- Bugs and feature requests: open an issue with a minimal reproduction.
- Security issues: follow [SECURITY.md](SECURITY.md) and report privately.

## License

By contributing, you agree that your contributions are licensed under the
project's MIT license (see [LICENSE](LICENSE)).
