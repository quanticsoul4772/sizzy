"""Federated memory store API (B5.5, §S7; Inv 17)."""

import json
import time
from uuid import uuid4

import msgspec

from devharness.events.registry import MemoryEntryCreated, MemoryEntryVerified
from devharness.memory.base import MemoryEntry, project_name


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def create_memory_entry(entry_type, entry_payload, conn, event_bus, *, correlation_id="memory", now_millis=None) -> str:
    """Create a LOCAL memory entry (this project is the source → trusted in this context). Emits
    memory_entry_created; returns the new entry_id."""
    entry_id = uuid4().hex
    event_bus.emit_sync(
        "memory_entry_created",
        msgspec.to_builtins(MemoryEntryCreated(
            entry_id=entry_id, entry_type=entry_type, entry_payload_json=json.dumps(entry_payload),
            source_project=project_name(), created_at_millis=_now(now_millis), correlation_id=correlation_id)),
        correlation_id=correlation_id,
    )
    return entry_id


def verify_memory_entry(entry_id, verifier_evidence, verified_by, conn, event_bus, *, correlation_id="memory", now_millis=None) -> None:
    """Promote a (typically imported, untrusted) entry to verified_locally — carrying the verification
    evidence naming the verifier that cleared it (Inv 17). Emits memory_entry_verified."""
    event_bus.emit_sync(
        "memory_entry_verified",
        msgspec.to_builtins(MemoryEntryVerified(
            entry_id=entry_id, verifier_evidence_json=json.dumps(verifier_evidence), verified_by=verified_by,
            verified_at_millis=_now(now_millis), correlation_id=correlation_id)),
        correlation_id=correlation_id,
    )


def list_verified_memory(conn, entry_type=None) -> list:
    """Entries this project TRUSTS (verified_locally=1), optionally filtered by entry_type."""
    sql = ("SELECT entry_id, entry_type, entry_payload_json, source_project, created_at_millis, correlation_id "
           "FROM proj_memory WHERE verified_locally = 1")
    params = ()
    if entry_type is not None:
        sql += " AND entry_type = ?"
        params = (entry_type,)
    sql += " ORDER BY memory_row_id"
    return [MemoryEntry(entry_id=r[0], entry_type=r[1], entry_payload=json.loads(r[2]), source_project=r[3],
                        created_at_millis=r[4], correlation_id=r[5]) for r in conn.execute(sql, params)]
