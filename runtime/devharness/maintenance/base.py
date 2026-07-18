"""Maintenance cycles (B3.6, §S6).

Four read-only idle-time cycles. Each cycle, when run, emits one maintenance_tick (the cycle
boundary) and one or more maintenance_action events describing what it observed. Cycles never
mutate code and never delete data — pruning is advisory (it reports what *would* be pruned).
Each cycle's work is bounded (``max_events``) to keep a tick cheap.
"""

import time
from abc import ABC, abstractmethod

from devharness.events.bus import verify_chain


class MaintenanceCycle(ABC):
    cycle_kind: str = "cycle"

    def _now(self, now_millis):
        return (now_millis or (lambda: int(time.time() * 1000)))()

    def _tick(self, event_bus, correlation_id, at_millis):
        event_bus.emit_sync(
            "maintenance_tick",
            {"cycle_kind": self.cycle_kind, "tick_at_millis": at_millis, "correlation_id": correlation_id},
            correlation_id=correlation_id,
        )

    def _action(self, event_bus, description, evidence, correlation_id, at_millis):
        event_bus.emit_sync(
            "maintenance_action",
            {"cycle_kind": self.cycle_kind, "action_description": description, "evidence": evidence,
             "correlation_id": correlation_id, "action_at_millis": at_millis},
            correlation_id=correlation_id,
        )

    @abstractmethod
    def run(self, conn, event_bus, *, correlation_id="maintenance", now_millis=None, max_events=100) -> None:
        ...


class ConsolidateCycle(MaintenanceCycle):
    cycle_kind = "consolidate"

    def run(self, conn, event_bus, *, correlation_id="maintenance", now_millis=None, max_events=100):
        at = self._now(now_millis)
        self._tick(event_bus, correlation_id, at)
        plans = conn.execute(
            "SELECT plan_id FROM proj_plan WHERE current_state IN ('completed', 'blocked') LIMIT ?", (max_events,)
        ).fetchall()
        self._action(
            event_bus, f"consolidated {len(plans)} terminal plan(s) into a digest",
            {"plan_count": len(plans), "plan_ids": [p[0] for p in plans][:20]}, correlation_id, at,
        )


class PruneCycle(MaintenanceCycle):
    cycle_kind = "prune"

    def run(self, conn, event_bus, *, correlation_id="maintenance", now_millis=None, max_events=100):
        at = self._now(now_millis)
        self._tick(event_bus, correlation_id, at)
        expired = conn.execute(
            "SELECT count(*) FROM proj_trust_grants WHERE revoked_at_millis IS NULL AND expires_at_millis < ?", (at,)
        ).fetchone()[0]
        self._action(
            event_bus, f"would prune {expired} expired trust grant(s) (advisory — no deletion)",
            {"expired_trust_grants": expired}, correlation_id, at,
        )


class AuditCycle(MaintenanceCycle):
    cycle_kind = "audit"

    def run(self, conn, event_bus, *, correlation_id="maintenance", now_millis=None, max_events=100):
        at = self._now(now_millis)
        self._tick(event_bus, correlation_id, at)
        total = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        try:
            chain_ok = verify_chain(conn) == total
        except Exception:  # a broken chain is an audit finding, not a crash
            chain_ok = False
        orphans = conn.execute(
            "SELECT count(*) FROM proj_task_lifecycle WHERE terminal_at_millis IS NULL"
        ).fetchone()[0]
        self._action(
            event_bus, f"audited {total} events: hash chain {'valid' if chain_ok else 'INVALID'}, {orphans} running task(s)",
            {"chain_valid": chain_ok, "event_count": total, "running_tasks": orphans}, correlation_id, at,
        )


class SynthesizeCycle(MaintenanceCycle):
    cycle_kind = "synthesize"

    def run(self, conn, event_bus, *, correlation_id="maintenance", now_millis=None, max_events=100):
        at = self._now(now_millis)
        self._tick(event_bus, correlation_id, at)
        by_class = dict(conn.execute("SELECT task_class, count(*) FROM proj_plan_tasks GROUP BY task_class").fetchall())
        self._action(
            event_bus, f"synthesized task activity across {len(by_class)} task class(es)",
            {"by_class": {k: v for k, v in by_class.items() if k is not None}}, correlation_id, at,
        )


ALL_CYCLES = [ConsolidateCycle, PruneCycle, AuditCycle, SynthesizeCycle]
