"""`devharness questions` — list pending (unanswered) interview questions.

The research interview emits each question as a `question_asked` event; the answer CLI only takes a
question_id you already know. This command shows the pending questions (every `question_asked` with no
matching `question_answered`) with their text, so the operator can SEE and answer them directly from a
terminal — no relay needed. Pairs with `devharness answer <question_id> <answer_text>`.
"""

import json
import sys


def pending_questions(conn) -> list:
    """[(question_id, question_text, correlation_id)] for every asked-but-unanswered question, oldest first."""
    asked = []
    for correlation_id, payload in conn.execute(
        "SELECT correlation_id, payload FROM events WHERE event_type = 'question_asked' ORDER BY seq"
    ):
        rec = json.loads(payload)
        asked.append((rec.get("question_id"), rec.get("question_text", ""), correlation_id))
    answered = {
        json.loads(p).get("question_id")
        for (p,) in conn.execute("SELECT payload FROM events WHERE event_type = 'question_answered'")
    }
    return [(qid, text, cid) for (qid, text, cid) in asked if qid not in answered]


def _format(qid, text, cid) -> str:
    """One question, with the parallax-elicit fields pulled out when present (else the raw text)."""
    header = f"=== {qid}  [{cid}] ==="
    try:
        obj = json.loads(text)
    except Exception:
        return f"{header}\n{text}"
    if not isinstance(obj, dict):
        return f"{header}\n{text}"
    lines = [header]
    if obj.get("assumed_objective"):
        lines.append(f"assumed objective: {obj['assumed_objective']}")
    for dp in obj.get("divergence_points", []) or []:
        q = dp.get("question") if isinstance(dp, dict) else None
        if q:
            lines.append(f"  - open question: {q}")
    if not obj.get("assumed_objective") and not obj.get("divergence_points"):
        lines.append(text)
    return "\n".join(lines)


def main(argv=None) -> int:
    import os

    from devharness.cli._bus import open_store
    conn = open_store()
    pend = pending_questions(conn)
    if not pend:
        print("(no pending questions)")
        return 0
    for qid, text, cid in pend:
        print(_format(qid, text, cid))
        print(f"answer with:  python -m devharness.cli.answer {qid} \"<your answer>\"")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
