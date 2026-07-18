"""Federated memory export/import (B5.5, §S7; OQ-B5-3=B). Operator-driven cross-project sync.

Export writes a portable JSON artifact of this project's memory entries (the memory_entry_created
payloads — NOT the verification state, since each project verifies independently per Inv 17). Import
replays those into the local store as **untrusted** (verified_locally=0). Import is idempotent (a
known entry_id is skipped) and monotonic (an entry older than the latest known one from the same
source_project is rejected — a downgrade-attack guard).
"""

import json
import time

from devharness.memory.base import project_name


def export_memory(target_path, conn, *, now_millis=None) -> int:
    """Write all proj_memory entries as a portable artifact. Returns the count exported."""
    rows = conn.execute(
        "SELECT entry_id, entry_type, entry_payload_json, source_project, created_at_millis, correlation_id "
        "FROM proj_memory ORDER BY memory_row_id"
    ).fetchall()
    entries = [{"entry_id": r[0], "entry_type": r[1], "entry_payload_json": r[2], "source_project": r[3],
                "created_at_millis": r[4], "correlation_id": r[5]} for r in rows]
    artifact = {
        "project_name": project_name(),
        "export_at_millis": (now_millis or (lambda: int(time.time() * 1000)))(),
        "entries": entries,  # memory_entry_created payloads; verification state is deliberately omitted
    }
    with open(target_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh)
    return len(entries)


def import_memory(artifact_path, conn, event_bus) -> int:
    """Replay an artifact's entries into the local store as untrusted; return the count imported."""
    with open(artifact_path, encoding="utf-8") as fh:
        artifact = json.load(fh)
    imported = 0
    for e in artifact.get("entries", []):
        # idempotent: a known entry_id is skipped (never downgraded / duplicated)
        if conn.execute("SELECT 1 FROM proj_memory WHERE entry_id = ?", (e["entry_id"],)).fetchone() is not None:
            continue
        # monotonic: reject an entry older than the latest known one from the same source_project
        latest = conn.execute(
            "SELECT max(created_at_millis) FROM proj_memory WHERE source_project = ?", (e["source_project"],)
        ).fetchone()[0]
        if latest is not None and e["created_at_millis"] < latest:
            continue  # downgrade-attack guard
        event_bus.emit_sync("memory_entry_created", {
            "entry_id": e["entry_id"], "entry_type": e["entry_type"], "entry_payload_json": e["entry_payload_json"],
            "source_project": e["source_project"], "created_at_millis": e["created_at_millis"],
        }, correlation_id=e.get("correlation_id") or "memory_import")
        imported += 1
    return imported
