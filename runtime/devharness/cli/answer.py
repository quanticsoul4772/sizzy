"""`devharness answer <question_id> <answer_text>` (B1.2).

Emits a question_answered event via EventBus.emit_sync, refusing an unknown
question_id (one with no matching question_asked in the event log). One CLI
command per operator-action surface (mirrors the B1.3 sign-off pattern).
"""

import json
import time

import msgspec

from devharness.events.registry import QuestionAnswered


class UnknownQuestion(RuntimeError):
    """Raised when answering a question_id with no matching question_asked event."""


def _correlation_for_question(conn, question_id):
    for correlation_id, payload in conn.execute(
        "SELECT correlation_id, payload FROM events WHERE event_type = 'question_asked'"
    ):
        if json.loads(payload).get("question_id") == question_id:
            return correlation_id
    return None


def answer_question(conn, event_bus, question_id, answer_text, *, now_millis=None) -> str:
    """Emit question_answered for an asked question; raise UnknownQuestion otherwise."""
    correlation_id = _correlation_for_question(conn, question_id)
    if correlation_id is None:
        raise UnknownQuestion(f"no question_asked event for question_id {question_id!r}")
    answered_at = (now_millis or (lambda: int(time.time() * 1000)))()
    payload = msgspec.to_builtins(
        QuestionAnswered(
            question_id=question_id,
            answer_text=answer_text,
            correlation_id=correlation_id,
            answered_at_millis=answered_at,
        )
    )
    event_bus.emit_sync("question_answered", payload, correlation_id=correlation_id)
    return question_id


def main(argv=None) -> int:
    import os
    import sys

    from devharness.cli._bus import open_store, projected_bus

    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        sys.stderr.write("usage: devharness answer <question_id> <answer_text>\n")
        return 2
    question_id, answer_text = argv
    conn = open_store()
    try:
        answer_question(conn, projected_bus(conn), question_id, answer_text)
    except UnknownQuestion as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
