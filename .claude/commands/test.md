---
description: Run the full test matrix (the 4 CI jobs) and report pass/fail per job.
---
Run the project's full test matrix — the same four jobs CI runs — and report each:

1. `python -m pytest tests/runtime -q -n auto` (the runtime suite, parallelized — ~18s vs ~52s)
2. `python -m pytest tests/specledger -q` (the specledger first-project tool)
3. `cargo test --test sidecar` from `sidecar/` (the Rust SSE sidecar)
4. `npm run check` from `dashboard/` (svelte-check)

If all pass, report the counts concisely. If any fail, show the failing test name(s) + the assertion and stop for instructions — do not auto-fix unless asked.
