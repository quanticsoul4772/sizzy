"""Forward-only SQLite migration runner (B0.1).

Applies numbered migrations from ``schema/migrations/`` in order, records applied
versions in ``schema_migrations``, and fails closed on a gap or out-of-order
sequence. Forward-only: migrations are never edited, renumbered, or reversed.
"""

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "schema" / "migrations"
_FILENAME = re.compile(r"^(\d{4})_.+\.sql$")


class MigrationError(RuntimeError):
    """Raised when the migration sequence is invalid; the runner fails closed."""


def discover(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[str, Path]]:
    """Return ``[(version, path)]`` for ``NNNN_*.sql`` files, ordered and contiguous from 0001."""
    found: dict[str, Path] = {}
    for path in migrations_dir.glob("*.sql"):
        match = _FILENAME.match(path.name)
        if match is None:
            raise MigrationError(f"migration filename not NNNN_*.sql: {path.name}")
        version = match.group(1)
        if version in found:
            raise MigrationError(f"duplicate migration version: {version}")
        found[version] = path
    ordered = [(v, found[v]) for v in sorted(found)]
    for expected, (version, _) in enumerate(ordered, start=1):
        if int(version) != expected:
            raise MigrationError(
                f"migration gap or misnumber: expected {expected:04d}, found {version}"
            )
    return ordered


def is_event_store(db_path) -> bool | None:
    """Whether ``db_path`` is a devharness event store — a read-only probe, tri-state.

    True: readable and carries the ``events`` table. False: POSITIVE evidence of not-a-store —
    the file is missing, is not a sqlite database, or its ``sqlite_master`` is readable without
    ``events``. None: exists but unreadable right now — a locked/WAL-contended REAL store must
    not be misclassified (every devharness store is WAL; ``cli/sweep.py`` exists because
    ``mode=ro`` can fail shared-memory setup against WAL, so the same two-step fallback is used
    here: ``mode=ro`` first, then a ``query_only`` connection).

    Never creates, never migrates (rev 0.4.13): the live defect was the deployed panel's notice
    naming ``parallax.db`` — the parallax MCP server's OWN database, co-located in ``var/`` by
    the VPS bootstrap — as the freshest store; every open path runs ``migrate()`` on connect,
    so treating a foreign sqlite file as a store writes devharness schema INTO it."""
    p = Path(db_path)
    if not p.is_file():
        return False
    query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
    try:
        conn = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return conn.execute(query).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        if not isinstance(exc, sqlite3.OperationalError):
            return False  # "file is not a database" — positive not-a-store evidence
    except Exception:
        return None
    try:
        # mode=rw: raises on a missing file (a plain connect would CREATE one if the file
        # vanished between is_file() and here — diff-review catch) while still allowing the
        # WAL -shm setup that mode=ro cannot do (the fallback's whole reason to exist).
        conn = sqlite3.connect(p.resolve().as_uri() + "?mode=rw", uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")  # writes rejected at the SQLite layer
            return conn.execute(query).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        if not isinstance(exc, sqlite3.OperationalError):
            return False
        return None  # unreadable right now — do not misclassify a locked real store
    except Exception:
        return None


def applied_versions(conn: sqlite3.Connection) -> list[str]:
    """Return recorded versions, ordered. Empty when ``schema_migrations`` is absent."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if exists is None:
        return []
    return [row[0] for row in conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )]


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in order; return the versions applied this run.

    Fails closed (``MigrationError``) when the on-disk sequence has a gap, or when the
    applied set is not a contiguous ``0001..k`` prefix of the on-disk sequence.
    """
    ordered = discover(migrations_dir)
    applied = applied_versions(conn)

    for expected, version in enumerate(applied, start=1):
        if int(version) != expected:
            raise MigrationError(
                f"applied set out of order: expected {expected:04d}, found {version}"
            )
    if len(applied) > len(ordered):
        raise MigrationError("more migrations recorded as applied than exist on disk")
    for version, _ in ordered[:len(applied)]:
        if version not in applied:
            raise MigrationError(f"migration {version} skipped while a later one is applied")

    newly_applied: list[str] = []
    for version, path in ordered[len(applied):]:
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()
        newly_applied.append(version)
    return newly_applied
