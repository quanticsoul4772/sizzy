"""Antibody library — text-only corpus of known-bad patterns (B5.2, §S7; Inv 11).

Antibodies are TEXT ONLY (Inv 11): the only payload beyond audit metadata is ``pattern_text``. No
callable, code blob, or eval target ever appears on an antibody event or in proj_antibody_library — a
retro output that proposes code is a gate-change, routed to the gate-change queue, never here. New
antibodies enter only via the operator-approval pipeline (approval.py).
"""

import time

import msgspec

from devharness.events.registry import AntibodyAdded, AntibodyRevoked


class Antibody(msgspec.Struct, frozen=True, kw_only=True):
    pattern_text: str  # non-empty (validated); the ONLY non-metadata field — antibodies are text only
    source_candidate_id: str  # the proj_antibody_queue row this was approved from
    added_at_millis: int
    added_by: str
    revoked_at_millis: int | None = None
    revoke_reason: str | None = None

    def __post_init__(self):
        if not self.pattern_text:
            raise ValueError("Antibody requires a non-empty pattern_text")


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def add_antibody(pattern_text, source_candidate_id, added_by, conn, event_bus, *, correlation_id="operator_review", now_millis=None) -> int:
    """Publish an approved antibody into the active library; emit antibody_added; return its row id."""
    if not pattern_text:
        raise ValueError("add_antibody requires a non-empty pattern_text")
    row_id = conn.execute("SELECT COALESCE(MAX(antibody_row_id), 0) + 1 FROM proj_antibody_library").fetchone()[0]
    at = _now(now_millis)
    event_bus.emit_sync(
        "antibody_added",
        msgspec.to_builtins(AntibodyAdded(
            antibody_row_id=row_id, pattern_text=pattern_text, source_candidate_id=source_candidate_id,
            added_by=added_by, added_at_millis=at, correlation_id=correlation_id)),
        correlation_id=correlation_id,
    )
    # B5.5 bridge: an approved antibody is also a local (trusted) cross-project memory entry. Both events
    # are pure-projection-handled (antibody_added -> proj_antibody_library; memory_entry_created -> proj_memory).
    from devharness.memory.store import create_memory_entry
    create_memory_entry("antibody", {"pattern_text": pattern_text}, conn, event_bus,
                        correlation_id=correlation_id, now_millis=lambda: at)
    return row_id


def revoke_antibody(antibody_row_id, reason, revoked_by, conn, event_bus, *, correlation_id="operator_review", now_millis=None) -> None:
    """Revoke an active antibody (it stops matching); emit antibody_revoked."""
    if not reason:
        raise ValueError("revoke_antibody requires a non-empty reason")
    event_bus.emit_sync(
        "antibody_revoked",
        msgspec.to_builtins(AntibodyRevoked(
            antibody_row_id=antibody_row_id, reason=reason, revoked_by=revoked_by,
            revoked_at_millis=_now(now_millis), correlation_id=correlation_id)),
        correlation_id=correlation_id,
    )


def list_active_antibodies(conn) -> list:
    """Active antibodies (not revoked), as Antibody structs."""
    rows = conn.execute(
        "SELECT pattern_text, source_candidate_id, added_at_millis, added_by, revoked_at_millis, revoke_reason "
        "FROM proj_antibody_library WHERE revoked_at_millis IS NULL ORDER BY antibody_row_id"
    ).fetchall()
    return [Antibody(pattern_text=r[0], source_candidate_id=r[1], added_at_millis=r[2], added_by=r[3],
                     revoked_at_millis=r[4], revoke_reason=r[5]) for r in rows]


def match_against_text(text: str, conn) -> list:
    """The pattern_text of every active antibody that occurs in ``text`` (substring match). Callable but
    not wired into any gate by default in B5.2; B5.4+ wires it into the retro/gate path."""
    if not text:
        return []
    return [ab.pattern_text for ab in list_active_antibodies(conn) if ab.pattern_text in text]
