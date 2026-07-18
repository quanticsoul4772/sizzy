# runtime/ — the Python harness

The core of devharness: the event store, projections, gates, verifiers, roles, and the learning spine.
See the [project README](../README.md) for the big picture and `devharness-spec.md` for the spec.

## What's inside (`devharness/`)

- `events/` — the typed event registry (`registry.py`, the `EVENT_TYPES` source of truth) and the
  `EventBus` (the sole writer to the hash-chained event log); `manifest.py` exports the dashboard's
  derived dispatch list.
- `projections/` — pure-projection handlers + the DELETE+replay rebuild-parity check (Invariant 8).
- `boot.py` / `migrate.py` — the 24-name boot-check ledger; the forward-only migration runner.
- `gates/` — fail-closed gates (workflow / secret / scope / sandbox / write-lock / spec-signed /
  verifier-attached, …) that deny known-bad intents with structured evidence.
- `verifier/` — per-task-class pass/fail acceptance checks (verifier-first acceptance).
- `roles/` — research / director / developer / reviewer, each a separate enforced tool surface;
  `synthesis.py` holds the research spec-body synthesis + director task-decomposition helpers.
- `task_classes/` — the BUILD classes + `maintenance`, with gate bindings and verifier refs.
- `lock/`, `worktree/`, `checkpoint/` — the single-writer lock, isolated worktrees, checkpoint/rewind.
- `oss/`, `sandbox/` — the §S5 OSS-contribution envelope and the multi-tier sandbox launcher.
- `retro/`, `memory/` — the learning spine: retro engine, antibody library, gate-change validator,
  approval pipeline, federated trusted memory.
- `cli/` — operator commands run as modules: `python -m devharness.cli.{sign,answer,retro,memory}`.

## Develop

```bash
pip install -e ".[test]"     # editable install with the test extra (msgspec + claude-agent-sdk + pytest)
pytest tests/runtime -q      # run from the repo root; ~940 tests (specledger's own 44 live in tests/specledger)
```

The package targets **Python 3.11+**. There is no separate lint step configured — correctness is enforced
by the test suite (the invariant audit, the boot ledger, rebuild parity, and the per-feature tests).

## Conventions

Projection handlers are pure (no event emission); projection tables avoid `AUTOINCREMENT` (rebuild
parity); event types are declared only in `events/registry.py`. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
for the full list and how to add a gate / event type / task class.
