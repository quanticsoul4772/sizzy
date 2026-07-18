"""`devharness work-items` — present discovered work-item candidates and record the operator's pick.

  (default / `list`)        print the pending candidates for the operator to choose from.
  `select <candidate_id>`   record the pick — a `question_answered` carrying the candidate_id against the
                            discovery pick-question — refusing an unknown id (id-validation).

Reuses the existing answer seam (no separate selection event). The operator picks in Claude Code; the
harness records the pick via this command.
"""

import json
import sys

from devharness.cli.answer import answer_question


def pending_candidates(conn) -> list:
    """[(candidate_id, title, kind, description, rationale)] for candidates not yet picked."""
    answered = {
        json.loads(p).get("answer_text")
        for (p,) in conn.execute("SELECT payload FROM events WHERE event_type='question_answered'")
    }
    rows = conn.execute(
        "SELECT candidate_id, title, kind, description, rationale FROM proj_work_item_queue "
        "ORDER BY work_item_row_id"
    ).fetchall()
    return [r for r in rows if r[0] not in answered]


def select_candidate(conn, event_bus, candidate_id) -> str:
    """Record the operator's pick: emit question_answered(answer_text=candidate_id) against the candidate's
    discovery pick-question. Refuses a candidate_id not in the queue (id-validation, retro precedent)."""
    row = conn.execute(
        "SELECT correlation_id FROM proj_work_item_queue WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"no work-item candidate {candidate_id!r} in the queue")
    return answer_question(conn, event_bus, f"{row[0]}-pick", candidate_id)


def main(argv=None) -> int:
    import os

    from devharness.cli._bus import open_store, projected_bus

    argv = list(sys.argv[1:] if argv is None else argv)
    conn = open_store()

    if argv and argv[0] == "select":
        if len(argv) != 2:
            sys.stderr.write("usage: devharness work-items select <candidate_id>\n")
            return 2
        try:
            select_candidate(conn, projected_bus(conn), argv[1])
        except ValueError as exc:
            sys.stderr.write(f"refused: {exc}\n")
            return 1
        print(f"selected {argv[1]}")
        return 0

    pend = pending_candidates(conn)
    if not pend:
        print("(no pending work-item candidates)")
        return 0
    for cid, title, kind, desc, rationale in pend:
        print(f"=== {cid}  [{kind}] {title} ===")
        print(f"  {desc}")
        if rationale:
            print(f"  why: {rationale}")
        print(f"  select with:  python -m devharness.cli.work_items select {cid}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
