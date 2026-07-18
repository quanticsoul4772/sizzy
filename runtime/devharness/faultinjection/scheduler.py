"""Loop-fault scheduler (feature B).

Runs the loop-fault probes inside the B3.6 maintenance window — it yields (runs nothing) while the
fermata holds (a writer holds the single lock or a task is live) and runs when it releases. Step-driven
for deterministic testing, like the adversarial scheduler.

Runs the WHOLE probe set per window (rev 0.3.89), not one probe round-robin: ``run_maintenance``
invokes ``drive()`` once per process (cron-style), and ``drive()`` constructs a fresh scheduler each
call — so an in-memory round-robin cursor would reset every invocation and only ever exercise the first
probe (the production gap the rev-0.3.88 live validation surfaced). Running all six per window closes
that at the cost of ~6 hermetic builds (real ``git init`` + worktree + a verifier subprocess each) per
maintenance pass — bounded by the fermata.
"""

from devharness.faultinjection.runner import run_all_loop_faults


class LoopFaultScheduler:
    def step(self, conn, event_bus, fermata, *, correlation_id="fault-injection", now_millis=None) -> bool:
        """Run the whole loop-fault probe set if the fermata is released; return True if it ran, else
        False (held)."""
        if fermata.is_held(conn):
            return False
        run_all_loop_faults(event_bus, correlation_id=correlation_id, now_millis=now_millis)
        return True
