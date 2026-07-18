"""Adversarial scheduler (B3.7).

Runs known-bad probes inside the B3.6 maintenance window — it yields (runs nothing) while the fermata
holds (a writer holds the single lock or a task is live) and runs when it releases. Step-driven for
deterministic testing, like the maintenance scheduler.

Runs the WHOLE probe set per window (rev 0.3.90), not one probe round-robin: run_maintenance invokes
drive() once per process (cron-style), constructing a fresh scheduler each call — so an in-memory
round-robin cursor reset every invocation and only the first gate probe ever ran in production (the
same per-process gap the rev-0.3.88 loop-fault validation surfaced). Gate probes are pure microsecond
gate.check calls, so running all is cheap — full coverage every window with no cost tradeoff.
"""

from devharness.adversarial.runner import run_all_probes


class AdversarialScheduler:
    def step(self, conn, event_bus, fermata, *, correlation_id="adversarial", now_millis=None) -> bool:
        """Run all known-bad probes if the fermata is released; return True if they ran, else False."""
        if fermata.is_held(conn):
            return False
        run_all_probes(conn, event_bus, correlation_id=correlation_id, now_millis=now_millis)
        return True
