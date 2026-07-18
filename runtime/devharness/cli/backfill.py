"""`devharness backfill <store>` — run the closed learning loop over a store's real history, on a SCRATCH
COPY (rev 0.3.96).

The real stores predate the invariant monitor (rev 0.3.87), so their logs carry no `invariant_violated`
signals and the signal-retro loop has never run on real data. Backfill snapshots the store, runs the monitor
sweep (emit `invariant_violated`) + the signal-retro drain (create gate-change candidates) on the COPY, and
NEVER writes the original — the corruption path (`emit_sync`'s non-atomic tail-hash read + append) is
eliminated, not merely guarded.

The snapshot is analysed as QUIESCENT: a frozen copy has no in-flight build (a historical orphan's
non-terminal lifecycle row is not a running task), so the drain's fermata gate is overridden — otherwise it
would no-op on the very orphan store it targets.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from devharness.cli._bus import projected_bus
from devharness.events.bus import verify_chain
from devharness.migrate import migrate
from devharness.monitor.sweep import run_invariant_sweep
from devharness.retro.engine import RetroEngine
from devharness.retro.signal_scheduler import SignalRetroScheduler

_SIGNAL_SIGNATURES = ("monitor_invariant_violated", "loop_fault_regression")


class QuiescentFermata:
    """A snapshot is offline analysis, not an in-flight build — always quiescent. This lets the signal-retro
    drain process a historical orphan (whose non-terminal lifecycle row would otherwise make the live
    fermata read as held, so the drain would no-op)."""

    def is_held(self, conn) -> bool:
        return False


def _open_readonly(resolved: Path) -> sqlite3.Connection:
    """Open READ-ONLY; prefer OS-level mode=ro, fall back to query_only against a WAL store."""
    try:
        conn = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM sqlite_master")  # force the open so a ro/WAL failure surfaces
        return conn
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(resolved))
        conn.execute("PRAGMA query_only = ON")
        return conn


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="devharness backfill",
        description="Run the monitor sweep + signal-retro drain over a store's history on a scratch COPY "
                    "(the original is never written).")
    parser.add_argument("store", help="path to the event store (.db) whose history to backfill")
    parser.add_argument("--out", help="output copy path (default: <store>.backfilled.db beside it)")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    resolved = Path(args.store).resolve()
    if not resolved.exists():
        sys.stderr.write(f"no event store at {resolved} — backfill does not create one\n")
        return 2
    out = Path(args.out).resolve() if args.out else resolved.with_name(resolved.stem + ".backfilled.db")
    if out.exists():
        out.unlink()  # a fresh snapshot each run

    # snapshot the READ-ONLY original into the fresh copy; the original is never written
    src = _open_readonly(resolved)
    dest = sqlite3.connect(str(out))
    try:
        src.backup(dest)
    finally:
        src.close()
    migrate(dest)  # bring the COPY (never the original) up so the drain's projection writes work

    bus = projected_bus(dest)
    signals = run_invariant_sweep(dest, bus)
    drain = SignalRetroScheduler(engine=RetroEngine(llm_fn=None), fermata=QuiescentFermata())
    while drain.step(dest, bus) is not None:
        pass
    placeholders = ", ".join("?" * len(_SIGNAL_SIGNATURES))
    candidates = dest.execute(
        f"SELECT COUNT(*) FROM proj_gate_change_queue WHERE signature_name IN ({placeholders})",
        _SIGNAL_SIGNATURES,
    ).fetchone()[0]
    verify_chain(dest)  # sanity: the copy's chain is intact
    dest.close()

    sys.stdout.write(f"emitted {len(signals)} signal(s), created {candidates} candidate(s) on the copy\n")
    sys.stdout.write(f"copy: {out}\n")
    sys.stdout.write(f"review with: DEVHARNESS_DB={out} devharness retro list-pending --queue gate-change\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
