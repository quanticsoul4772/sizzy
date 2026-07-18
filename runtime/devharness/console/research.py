"""Operator console research action — start a session and submit interview answers.

The operator drives research directly, with no LLM agent in the seat: ``start_research``
issues the ``research_started`` operation, ``ask_question`` records an interview prompt
(``question_asked``), and ``submit_answer`` records the operator's answer
(``question_answered``) — the SAME operations the ``run_research`` driver and the
``devharness answer`` CLI issue, but each recorded with the operator's identity so the event
log attributes the action to the human in the seat (the ``operator`` payload field, mirroring
the ``signer`` attribution on ``spec_signed``).

Every write goes through ``EventBus.emit_sync`` — the console's sole sanctioned write path —
never a direct event-store or projection write. Lookups are SELECT-only.
"""

import json
import time
from uuid import uuid4

import msgspec

from devharness.cli.sign import operator_identity
from devharness.events.registry import QuestionAnswered, QuestionAsked, ResearchStarted


class UnknownQuestion(RuntimeError):
    """Raised when answering a question_id with no matching question_asked event."""


class ConsoleResearch:
    """Operator-driven research actions, emitting operator-attributed events via emit_sync.

    Constructed against the console's connection and its ``EventBus`` writer (the emit-only
    write path). ``operator`` defaults to the harness operator identity
    (``DEVHARNESS_OPERATOR`` env, else ``git config user.name``) and can be overridden per
    instance or per call.
    """

    def __init__(self, conn, writer, *, operator=None, now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        self._operator = operator
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def _resolve_operator(self, operator) -> str:
        return operator or self._operator or operator_identity()

    def _emit(self, event_type, struct, correlation_id, operator) -> None:
        """Emit a research event through EventBus.emit_sync, tagged with the operator identity."""
        payload = msgspec.to_builtins(struct)
        payload["operator"] = operator  # operator-attributed (the human in the seat, not an LLM)
        self._writer.emit_sync(event_type, payload, correlation_id=correlation_id)

    def start_research(self, topic, *, correlation_id=None, operator=None) -> str:
        """Begin a research session: emit research_started, return the research_id.

        The research_id IS the correlation_id (as in run_research, where ``research_id =
        correlation_id``). A fresh hex id is minted when none is supplied.
        """
        operator = self._resolve_operator(operator)
        research_id = correlation_id or uuid4().hex
        self._emit(
            "research_started",
            ResearchStarted(research_id=research_id, topic=topic[:120]),
            research_id,
            operator,
        )
        return research_id

    def ask_question(self, research_id, question_text, *, operator=None) -> str:
        """Record an operator interview question (question_asked); return its question_id.

        The id matches the run_research convention: ``<research_id>-q<N>`` where N is the
        count of questions already asked for this research session.
        """
        operator = self._resolve_operator(operator)
        question_id = f"{research_id}-q{self._question_count(research_id)}"
        self._emit(
            "question_asked",
            QuestionAsked(research_id=research_id, question_id=question_id, question_text=question_text),
            research_id,
            operator,
        )
        return question_id

    def submit_answer(self, question_id, answer_text, *, operator=None) -> str:
        """Submit an operator answer (question_answered); refuse an unknown question_id.

        Mirrors the ``devharness answer`` CLI: an answer is only recorded against a question
        that was actually asked (a matching ``question_asked`` event), and inherits that
        question's correlation_id.
        """
        operator = self._resolve_operator(operator)
        correlation_id = self._correlation_for_question(question_id)
        if correlation_id is None:
            raise UnknownQuestion(f"no question_asked event for question_id {question_id!r}")
        self._emit(
            "question_answered",
            QuestionAnswered(
                question_id=question_id,
                answer_text=answer_text,
                correlation_id=correlation_id,
                answered_at_millis=self._now_millis(),
            ),
            correlation_id,
            operator,
        )
        return question_id

    # --- read-only lookups (SELECT-only; no event-store or projection writes) ---

    def _question_count(self, research_id) -> int:
        count = 0
        for (payload,) in self._conn.execute(
            "SELECT payload FROM events WHERE event_type = 'question_asked'"
        ):
            if json.loads(payload).get("research_id") == research_id:
                count += 1
        return count

    def _correlation_for_question(self, question_id):
        for correlation_id, payload in self._conn.execute(
            "SELECT correlation_id, payload FROM events WHERE event_type = 'question_asked'"
        ):
            if json.loads(payload).get("question_id") == question_id:
                return correlation_id
        return None
