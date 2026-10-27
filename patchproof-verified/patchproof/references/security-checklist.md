# PatchProof security checklist

Apply to every change before it is reported. Findings go into the report's
`findings` array with a severity and evidence; distinguish **confirmed**
vulnerabilities (demonstrated against the code or an isolated repro) from
**suspected** risks (reasoned but not demonstrated).

## Input handling

- Injection: SQL, OS command, template, and shell injection in any new or
  modified input path. Check that values are parameterized or escaped at the
  right boundary.
- Deserialization: parsing untrusted input with pickle/yaml.load/eval-like
  facilities. Prefer safe loaders or avoid entirely.
- Path handling: user-controlled paths used in file operations. Check for
  traversal (`..`, absolute paths) and for symlink surprises.
- HTML output: XSS via unescaped interpolation in templates or `innerHTML`.

## Authentication and authorization

- Does the change bypass an authn/authz check, widen a permission, or move a
  check to a place where it can be skipped?
- Are new endpoints or functions protected at the same level as their peers?

## Secrets and sensitive data

- No credentials, tokens, or private keys in code, config committed to the
  repo, test fixtures, logs, or the verification report. The report
  validator rejects reports containing secret material.
- No new logging of sensitive fields (passwords, tokens, PII).
- Do not send private source code or sensitive logs to external AI providers
  without explicit user authorization.

## Filesystem and processes

- File writes: race conditions (TOCTOU), temp files with predictable names,
  permissions too broad.
- Command execution: subprocess calls built from user input without proper
  argument arrays (avoid shell=True with concatenated strings).
- Resource limits: unbounded loops, decompression bombs, or downloads in the
  changed path.

## Dependencies

- New dependencies must be justified by the change. Prefer standard library
  and existing dependencies.
- If a dependency was added, note its maintenance status and whether it pulls
  transitive risk; run the project's audit tool if one exists
  (e.g. `pip-audit`, `npm audit`, `cargo audit`) and record the result as a
  check — SKIPPED with reason if the tool is unavailable.

## Verification of findings

- Validate each finding against the actual code and execution context, not
  just a pattern match. A regex hit is a lead, not a finding.
- For each finding, record evidence: the vulnerable lines, the input that
  triggers it, or the tool output.
- Classify honestly: a confirmed vulnerability is a finding with severity;
  an unproven concern goes in `limitations`, or as an `info`-severity finding
  explicitly labeled suspected.

## Working on hostile repositories

- For untrusted code (downloaded samples, malware research, exploit PoCs):
  recommend an isolated execution environment (VM, container without network
  or shared mounts) and never execute the code on the host.
- Do not exploit production systems, scan systems you do not own, or access
  unrelated private resources.
