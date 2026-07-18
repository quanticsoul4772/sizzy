"""Loop-fault probe registry (feature B).

Each probe injects one real failure class at an EXISTING developer seam and declares the terminal the
harness SHOULD reach. The oracle is monitor-only (a fired ``invariant_violated`` is the regression),
so ``expected_terminal`` is documentation, not an assertion — the per-class expected-terminal check is
deferred to a later B2.

The six MVP faults are exactly the ones that hurt real console builds this session:
  - ``mid_dispatch_crash``   — the worker crashes mid-write            (rev-0.3.86 #4: crash → abort)
  - ``git_checkpoint_128``   — a baseline checkpoint git op exits 128  (rev-0.3.86 #6: identity fallback)
  - ``hard_sdk_crash``       — the coding-worker SDK session errors    (Inv 10: no silent orphan)
  - ``transient_sdk_glitch`` — the transient "error result: success"   (rev-0.3.86 #7: bounded retry)
  - ``missing_test_runner``  — the verifier's test binary is absent    (missing python/pytest on the box)
  - ``worktree_collision``   — worktree creation fails                 (pre-start fault → clean abort)

Seam ordering (``roles/developer.py``): ``worktree_factory`` runs BEFORE ``task_started``;
``checkpoint_fn``, ``write_hook`` and ``query_fn`` run AFTER it. Only a POST-``task_started`` seam can
orphan a task, so those are the ones the regression proof injects into.
"""

import subprocess
from typing import Callable

import msgspec

from devharness.mcp.base import TRANSIENT_SDK_RESULT


class LoopFaultProbe(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    fault_class: str
    # patch(dev_kwargs) mutates the base developer_kwargs in place to inject the fault.
    patch: Callable
    spec_claim_retries: int = 0
    test_command: list | None = None  # override the verifier's test command (missing_test_runner)
    expected_terminal: str = "aborted"  # documentation only (monitor-only oracle)


class ProbeRegistrationError(RuntimeError):
    """Raised when registering a probe name that is already registered."""


PROBES: dict[str, LoopFaultProbe] = {}


def register_probe(probe: LoopFaultProbe) -> None:
    if probe.name in PROBES:
        raise ProbeRegistrationError(f"loop-fault probe {probe.name!r} already registered")
    PROBES[probe.name] = probe


def clear_probes() -> None:
    """Test-isolation helper (the registry is module-global)."""
    PROBES.clear()


# --- fault seams (each mutates the base developer_kwargs) ---

def _raiser(exc):
    def _fault(*args, **kwargs):
        raise exc
    return _fault


def _async_raiser(exc):
    def _query(*, prompt, options):
        async def _gen():
            raise exc
            yield  # noqa: unreachable — makes this an async generator
        return _gen()
    return _query


def _crash_write_hook(dev_kwargs) -> None:
    dev_kwargs["write_hook"] = _raiser(RuntimeError("injected mid-dispatch worker crash"))


def _checkpoint_128(dev_kwargs) -> None:
    dev_kwargs["checkpoint_fn"] = _raiser(
        subprocess.CalledProcessError(128, ["git", "commit", "-m", "checkpoint"])
    )


def _hard_sdk_crash(dev_kwargs) -> None:
    # the coding-worker SDK session raises when iterated (NOT the transient variant → not retried)
    dev_kwargs["query_fn"] = _async_raiser(RuntimeError("injected hard SDK failure"))


def _transient_then_clean(dev_kwargs) -> None:
    # attempt 0 raises the transient "error result: success" glitch; the retry writes cleanly.
    from devharness.faultinjection.hermetic import clean_write_hook

    state = {"tries": 0}

    def _hook(editor, shell, test_runner):
        if state["tries"] == 0:
            state["tries"] += 1
            raise RuntimeError(f"the coding worker {TRANSIENT_SDK_RESULT}")
        clean_write_hook(editor, shell, test_runner)

    dev_kwargs["write_hook"] = _hook


def _worktree_collision(dev_kwargs) -> None:
    dev_kwargs["worktree_factory"] = _raiser(RuntimeError("injected worktree collision"))


def _noop_patch(dev_kwargs) -> None:
    pass  # missing_test_runner injects via test_command, not a dev-kwargs seam


def register_builtin_probes() -> None:
    builtin = [
        LoopFaultProbe(name="mid_dispatch_crash", fault_class="worker_crash", patch=_crash_write_hook),
        LoopFaultProbe(name="git_checkpoint_128", fault_class="git_128", patch=_checkpoint_128),
        LoopFaultProbe(name="hard_sdk_crash", fault_class="sdk_error", patch=_hard_sdk_crash),
        LoopFaultProbe(name="transient_sdk_glitch", fault_class="sdk_transient",
                       patch=_transient_then_clean, spec_claim_retries=1, expected_terminal="completed"),
        LoopFaultProbe(name="missing_test_runner", fault_class="missing_runner", patch=_noop_patch,
                       test_command=["devharness-no-such-test-runner", "app.py"]),
        LoopFaultProbe(name="worktree_collision", fault_class="worktree_fail", patch=_worktree_collision),
    ]
    for probe in builtin:
        if probe.name not in PROBES:
            register_probe(probe)


register_builtin_probes()
