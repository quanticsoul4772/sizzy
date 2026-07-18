"""scope_guard gate (§S5 OSS fear-map; real body B4.2).

Blocks a contribution whose cumulative net LOC (lines added minus lines removed across the diff)
exceeds the limit (default 500, §S5; configurable per task or via env). Large OSS changes are hard
for a maintainer to review and risky to land. Override: `allow_large_change`
(`scope_guard_override=True`). This is the cumulative-LOC gate — DISTINCT from the B2.1 `scope_gate`
(glob file-boundary); both can fire on an OSS task, each enforcing a different sensitivity.
"""

import os

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate

DEFAULT_SCOPE_LOC_LIMIT = 500


def _limit(context: dict) -> int:
    if context.get("scope_guard_limit") is not None:
        return int(context["scope_guard_limit"])
    env = os.environ.get("DEVHARNESS_OSS_SCOPE_LOC_LIMIT")
    return int(env) if env else DEFAULT_SCOPE_LOC_LIMIT


def cumulative_churn_loc(diff_content: str) -> int:
    """Total CHURN = added PLUS removed (audit F6): the review burden is every changed line, not the net.
    NET (added - removed) understated reviewability — a 5000-add/4600-remove change nets 400 but is 9600
    lines to review, and a delete-and-readd gamed the cap. Counts unified-diff body lines, ignores
    headers + binaries."""
    added = removed = 0
    for line in (diff_content or "").splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@") or line.startswith("diff "):
            continue
        if line.startswith("Binary files") and line.endswith("differ"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added + removed


class ScopeGuard(Gate):
    name = "scope_guard"

    def check(self, context: dict):
        diff = context.get("diff_content", "") or ""
        churn = cumulative_churn_loc(diff)
        limit = _limit(context)
        if churn <= limit:
            return GateOk()
        if context.get("scope_guard_override") is True:
            return GateOk(reason="loc_over_limit_with_override")
        return GateDeny(
            reason=f"loc_over_limit: cumulative churn LOC {churn} exceeds {limit}",
            purpose="OSS contributions stay small enough for a maintainer to review (§S5 scope_guard, cumulative churn LOC)",
            fix="Split the change into smaller PRs, or attach an approved allow_large_change override",
            evidence={"cumulative_churn_loc": churn, "limit": limit},
        )


register_gate("scope_guard", ScopeGuard())
