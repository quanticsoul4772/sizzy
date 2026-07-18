"""`devharness retro …` — the operator review CLI for retro CANDIDATEs (B5.4, §S7).

Subcommands:
  devharness retro list-pending [--queue antibody|gate-change|all] [--limit N]
  devharness retro approve <queue> <candidate_row_id>
  devharness retro reject  <queue> <candidate_row_id> --reason TEXT

Reviewer identity: DEVHARNESS_OPERATOR_ID env, else the current OS user. setting_sources=[] (no LLM in
the CLI path — operator review is deterministic). Blocking review (OQ-B5-2=A): a CANDIDATE stays pending
until an explicit approve/reject; there is no auto-archive.
"""

import argparse
import getpass
import os

from devharness.retro.approval import (
    approve_antibody_candidate,
    approve_gate_change_candidate,
    reject_antibody_candidate,
    reject_gate_change_candidate,
)

_QUEUES = {"antibody", "gate-change"}


def reviewer_identity() -> str:
    return os.environ.get("DEVHARNESS_OPERATOR_ID") or getpass.getuser()


def list_pending(conn, *, queue="all", limit=50) -> list:
    """Return pending CANDIDATEs across the requested queue(s): a list of display dicts."""
    out = []
    if queue in ("antibody", "all"):
        for r in conn.execute(
            "SELECT antibody_row_id, signature_name, pattern_text, source, created_at_millis "
            "FROM proj_antibody_queue WHERE review_state = 'pending' ORDER BY created_at_millis LIMIT ?", (limit,)
        ):
            out.append({"queue": "antibody", "candidate_row_id": r[0], "signature_name": r[1],
                        "detail": r[2], "source": r[3], "created_at_millis": r[4]})
    if queue in ("gate-change", "all"):
        for r in conn.execute(
            "SELECT gate_change_row_id, signature_name, target_gate, change_kind, source, created_at_millis "
            "FROM proj_gate_change_queue WHERE review_state = 'pending' ORDER BY created_at_millis LIMIT ?", (limit,)
        ):
            out.append({"queue": "gate-change", "candidate_row_id": r[0], "signature_name": r[1],
                        "detail": f"{r[2]} / {r[3]}", "source": r[4], "created_at_millis": r[5]})
    return out


def _conn():
    from devharness.cli._bus import open_store
    return open_store()


def main(argv=None) -> int:
    import sys

    from devharness.cli._bus import projected_bus

    parser = argparse.ArgumentParser(prog="devharness retro")
    sub = parser.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("list-pending")
    lp.add_argument("--queue", choices=["antibody", "gate-change", "all"], default="all")
    lp.add_argument("--limit", type=int, default=50)
    ap = sub.add_parser("approve")
    ap.add_argument("queue", choices=sorted(_QUEUES))
    ap.add_argument("candidate_row_id", type=int)
    rj = sub.add_parser("reject")
    rj.add_argument("queue", choices=sorted(_QUEUES))
    rj.add_argument("candidate_row_id", type=int)
    rj.add_argument("--reason", required=True)

    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    conn = _conn()
    bus = projected_bus(conn)
    who = reviewer_identity()

    if args.cmd == "list-pending":
        rows = list_pending(conn, queue=args.queue, limit=args.limit)
        for r in rows:
            sys.stdout.write(f"[{r['queue']}] #{r['candidate_row_id']} ({r['source']}) {r['signature_name'] or '-'}: {r['detail']}\n")
        if not rows:
            sys.stdout.write("no pending candidates\n")
        return 0

    try:
        if args.cmd == "approve":
            (approve_antibody_candidate if args.queue == "antibody" else approve_gate_change_candidate)(args.candidate_row_id, who, conn, bus)
        else:  # reject
            (reject_antibody_candidate if args.queue == "antibody" else reject_gate_change_candidate)(args.candidate_row_id, who, args.reason, conn, bus)
    except Exception as exc:  # noqa: BLE001 — surface the refusal to the operator
        sys.stderr.write(f"refused: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
