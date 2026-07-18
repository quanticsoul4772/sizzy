"""`devharness ratify` — recommend evidence-based per-class blast-radius caps from realized telemetry (Track 3).

Reads `write_applied` events from the event DB and prints, per write-class, the realized blast radius and a
recommended cap (or `insufficient_samples`). It only reports — applying a recommendation to
`task_classes/builtin.py` stays a deliberate operator act.
"""

import os
import sys
from pathlib import Path

from devharness.cli._bus import open_store
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.ratify import format_report, ratify_blast_radius_caps


def main(argv=None) -> int:
    # argv accepted for the dispatcher contract; no flags yet
    if not Path(db).exists():
        print(f"devharness ratify: no event DB at {db}", file=sys.stderr)
        return 1
    register_builtin_task_classes()
    conn = open_store()
    print(format_report(ratify_blast_radius_caps(conn)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
