"""Verifier runner (B2.2). The path that emits verifier_outcome.

Direct Verifier.verify() calls are discouraged outside this runner; the runner is
what records the outcome + evidence into the event log.
"""

import msgspec

from devharness.events.registry import VerifierOutcome
from devharness.verifier.base import VerifierOk
from devharness.verifier.registry import FALSIFIERS


class UnknownVerifier(RuntimeError):
    """Raised when running a verifier_name with no registered falsifier."""


async def run_verifier(verifier_name: str, context: dict, event_bus, conn, *, lifecycle=None, checkpoint=None,
                       terminal_on_fail=True):
    """Run a registered verifier, emit verifier_outcome with evidence, return the result.

    When the verifier fails and both ``lifecycle`` and ``checkpoint`` are supplied, the
    verifier-failure auto-rewind (B2.6) fires before the verdict propagates further. With
    ``terminal_on_fail=False`` a spec-claim deviation OR a missing-test-coverage failure is treated as
    RETRYABLE: the worktree is rewound but the task is left non-terminal (no terminal_outcome) so the
    bounded auto-retry can re-run it. Both are self-correctable by the worker on retry; a genuine
    test_suite or spec_criteria failure is not and stays terminal.
    """
    verifier = FALSIFIERS.get(verifier_name)
    if verifier is None:
        raise UnknownVerifier(f"no verifier registered as {verifier_name!r}")
    result = await verifier.verify(context)
    passed = isinstance(result, VerifierOk)
    event_bus.emit_sync(
        "verifier_outcome",
        msgspec.to_builtins(
            VerifierOutcome(
                task_id=context.get("task_id", "<unknown>"),
                verifier=verifier_name,
                passed=passed,
                detail="" if passed else result.reason,
                evidence=result.evidence,
            )
        ),
        correlation_id=context.get("correlation_id"),
    )
    if not passed and lifecycle is not None and checkpoint is not None:
        from devharness.task_lifecycle.auto_rewind import on_verifier_failure

        # a spec-claim deviation or a missing-test-coverage failure, with attempts left, is RETRYABLE
        # (non-terminal rewind so the worker self-corrects); any other failure, or the final attempt, is
        # a terminal reject.
        reason = getattr(result, "reason", "") or ""
        retryable = (not terminal_on_fail) and ("spec_claim axis" in reason or "test_coverage axis" in reason)
        on_verifier_failure(context.get("task_id"), lifecycle, checkpoint, event_bus, conn, retryable=retryable)
    return result
