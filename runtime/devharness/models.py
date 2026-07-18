"""Single source of truth for the harness's model selection.

The cost-tier system (T0-T3) is a structural floor enforced at dispatch (Invariant 16). ``model_for_tier``
(rev 0.3.82) is the tier->model router the spec flagged as a follow-up: it maps each tier to a concrete
model so advisory/exploration traffic runs a cheaper model while the single writer and the
done-earned-twice quality gate stay frontier. ``DEVHARNESS_MODEL`` pins the whole process (overriding the
ladder); an explicit ``model=`` kwarg at a construction site still wins over both.

This is the only file exempt from the no-hardcoded-model-ids guard test, so every literal model id lives
here — everywhere else routes through ``default_model()`` / ``model_for_tier()``.
"""

import os

_FRONTIER = "claude-fable-5"   # T2/T3: the single writer + the verifier/reviewer quality gate
_ADVISORY = "claude-sonnet-5"  # T0/T1: cheap exploration — research, retro residue, scope widening

# The tier->model ladder (§S2): T3 frontier, T2 mid/writer (kept frontier — the operator moved to Fable 5
# deliberately), T1 cheap advisory, T0 deterministic/no-LLM (a safe cheap default if ever consulted).
_TIER_MODELS = {"T3": _FRONTIER, "T2": _FRONTIER, "T1": _ADVISORY, "T0": _ADVISORY}


def default_model() -> str:
    """The frontier default: DEVHARNESS_MODEL override, else the built-in T2/T3 model."""
    return os.environ.get("DEVHARNESS_MODEL", _FRONTIER)


def model_for_tier(tier: str) -> str:
    """The concrete model for a cost tier. DEVHARNESS_MODEL pins the whole process (overrides the
    ladder); otherwise T2/T3 -> frontier, T0/T1 -> the cheaper advisory model. An unknown tier falls
    back to the frontier default (fail safe: never silently downgrade an unrecognized tier)."""
    override = os.environ.get("DEVHARNESS_MODEL")
    if override:
        return override
    return _TIER_MODELS.get(tier, _FRONTIER)
