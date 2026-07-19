"""Retro context + result types (B5.0, §S7)."""

import msgspec


class RetroContext(msgspec.Struct, frozen=True, kw_only=True):
    """The terminal context a retro run analyzes — assembled by the harness from the event log."""
    terminal_outcome_event: dict  # the terminal_outcome payload that triggered this retro
    preceding_events: list  # the events (same correlation_id) leading up to the terminal, in order
    calibration_snapshot: dict  # Brier + trust grants at terminal time (B5.1 fills; B5.0 minimal)
    source_task_id: str
    correlation_id: str
    verifier_outcome: dict | None = None  # the task's verifier_outcome payload, if any
    reviewer_certification: dict | None = None  # the task's reviewer_certified payload, if any


class RetroResult(msgspec.Struct, frozen=True, kw_only=True):
    """What a retro run produced — candidate identifiers + a summary. (B5.0 stub returns empty.)"""
    candidates_emitted: list  # candidate identifiers (B5.1 fills)
    summary: str
    # B5.1 additive: the engine's run shape, folded into the retro_run event by the scheduler
    t0_matched_signatures: list = []
    llm_invoked: bool = False
    candidate_kinds: list = []
    # rev 0.4.24 additive: candidates the duplicate-candidate guard suppressed pre-emit (conn threaded)
    candidates_suppressed_count: int = 0
