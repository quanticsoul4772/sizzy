"""Maintenance scheduler (B3.6, §S6).

Drives the fermata loop one step at a time. A step yields (runs nothing) while the fermata holds
— maintenance never runs while a writer holds the single lock or a task is live. When the fermata
releases, the step runs the deepest cycle unlocked by the current idle duration (graduated
pressure). The scheduler is injectable + step-driven so tests advance it deterministically rather
than spawning a background thread.
"""

from devharness.maintenance.base import AuditCycle, ConsolidateCycle, PruneCycle, SynthesizeCycle
from devharness.maintenance.fermata import FermataPacing


class MaintenanceScheduler:
    def __init__(self, cycles=None, fermata=None):
        if cycles is None:
            cycles = [ConsolidateCycle(), PruneCycle(), AuditCycle(), SynthesizeCycle()]
        self.cycles = {c.cycle_kind: c for c in cycles}
        self.fermata = fermata or FermataPacing()

    def step(self, conn, event_bus, *, idle_millis, correlation_id="maintenance", now_millis=None) -> str | None:
        """Run at most one maintenance cycle. Returns the cycle_kind run, or None if held/too-soon.

        Yields (returns None, runs nothing) whenever the fermata holds — i.e. the write lock is held
        or a task is still running. Otherwise runs the deepest cycle unlocked at ``idle_millis``.
        """
        if self.fermata.is_held(conn):
            return None
        cycle_kind = self.fermata.deepest_cycle(idle_millis)
        if cycle_kind is None:
            return None
        self.cycles[cycle_kind].run(conn, event_bus, correlation_id=correlation_id, now_millis=now_millis)
        return cycle_kind
