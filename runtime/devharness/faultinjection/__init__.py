"""Loop fault-injection (feature B, spec rev 0.3.88).

The adversarial self-tester (``devharness/adversarial/``) probes each *gate's* deny path. This
extends the same idea to the whole *loop*: deliberately inject the failure classes that hurt real
builds — a mid-dispatch crash, a git-commit-128, a missing test runner, a transient/hard SDK error,
a worktree collision — into a HERMETIC build (a throwaway in-memory store + temp git repo, never the
operator's live log) and assert the harness handles each gracefully.

The oracle is the live invariant monitor (``devharness/monitor/``): a fault the harness turns into a
clean ``aborted``/``completed`` terminal emits NO ``invariant_violated``; a fault that silently
orphans the task fires an Inv-10 violation. So a *fault-handling regression* = the sweep fires after
an injected fault. These probes lock in the rev-0.3.86 fixes (#4 crash→abort, #6 identity fallback,
#7 transient retry): a future change that regresses them is caught by the probe's own sweep.
"""
