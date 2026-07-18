"""Live invariant monitor — turns the behaviorally-checkable invariants into live guards.

The 18 invariants are enforced at test time (structure); this package checks the 7 that are decidable
from the event log AT RUNTIME (behavior) and emits an ``invariant_violated`` event the moment one breaks.
The worst defect of the first real panel-driven build was silent — a ``task_started`` with no
``terminal_outcome`` that looped invisibly (a live Inv-10 breach) — exactly the class this catches.

``checks`` holds the per-invariant checks (each reusing an existing helper); ``sweep.run_invariant_sweep``
runs them over the log, dedups against already-reported violations, and emits at TOP LEVEL (never from a
projection handler — that would re-enter ``emit_sync`` mid-transaction and corrupt the hash chain).
"""
