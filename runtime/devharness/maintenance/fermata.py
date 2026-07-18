"""Fermata pacing (B3.6, §S6).

A fermata (musical: a held pause) governs the maintenance loop. While active work is in flight —
the single-writer lock is held, or a task has started without a terminal — maintenance is HELD and
no cycle runs. When work concludes, the hold releases. A graduated-pressure protocol then unlocks
progressively deeper cycles as idle time grows: gentle (consolidate) first, then prune, audit, and
finally synthesize.
"""

# default idle thresholds (ms) at which each cycle becomes available
DEFAULT_THRESHOLDS = {
    "consolidate": 60_000,
    "prune": 300_000,
    "audit": 900_000,
    "synthesize": 3_600_000,
}


class FermataPacing:
    def __init__(self, thresholds=None):
        self.thresholds = dict(thresholds or DEFAULT_THRESHOLDS)

    def active_work(self, conn) -> bool:
        """True iff a writer holds the lock or a started task has not reached a terminal."""
        if conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] > 0:
            return True
        running = conn.execute(
            "SELECT count(*) FROM proj_task_lifecycle WHERE terminal_at_millis IS NULL"
        ).fetchone()[0]
        return running > 0

    def is_held(self, conn) -> bool:
        """The fermata holds (maintenance paused) while there is active work."""
        return self.active_work(conn)

    def unlocked_cycles(self, idle_millis: int) -> list[str]:
        """The cycle kinds available at this idle duration, gentlest first (graduated pressure)."""
        ordered = sorted(self.thresholds.items(), key=lambda kv: kv[1])
        return [kind for kind, threshold in ordered if idle_millis >= threshold]

    def deepest_cycle(self, idle_millis: int) -> str | None:
        """The deepest cycle unlocked at this idle duration, or None if still too soon."""
        unlocked = self.unlocked_cycles(idle_millis)
        return unlocked[-1] if unlocked else None
