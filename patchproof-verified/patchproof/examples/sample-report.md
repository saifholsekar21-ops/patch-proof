# PatchProof verification report

- Task: `PP-DEMO-001` — Demonstrate patchproof verify on the bundled demo project
- PatchProof: `1.1.0`
- Generated: 2026-10-26T18:02:28+00:00
- Overall status: **passed**

## Repository

- Path: `C:\Users\HP\Documents\Qoder\2026-10-26\996ce3be\patchproof\examples\demo-project` · revision: `unknown` · branch: `unknown` · dirty: None
- Change selection: `none`

## Checks

| ID | Category | Status | Exit | Duration | Tool |
|----|----------|--------|------|----------|------|
| secrets | secrets (required) | passed | - | - | patchproof-secrets |
| custom:unit-tests | custom (required) | passed | 0 | 0.184s | python |

### secrets — internal repository scan (regex patterns; see SECURITY.md)

```
no credential patterns found in scanned files
```

### custom:unit-tests — C:\Users\HP\Documents\Qoder\2026-10-26\996ce3be\patchproof\.venv\Scripts\python.exe -m unittest discover -q

```
----------------------------------------------------------------------
Ran 1 test in 0.000s
OK
```

## Limitations

- 'C:\\Users\\HP\\Documents\\Qoder\\2026-10-26\\996ce3be\\patchproof\\examples\\demo-project' is not a git repository; no change analysis performed
- checks execute with the invoking user's privileges; no sandboxing is performed (run PatchProof inside an isolated environment for untrusted code)
