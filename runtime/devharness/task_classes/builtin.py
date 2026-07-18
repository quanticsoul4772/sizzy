"""Built-in task classes (B2.1; OQ3 ratified at B2.8).

B2 ships the first write-authority class, `new_project_scaffold`. Registering it at
import populates `TASK_CLASSES`; `register_builtin_task_classes()` is idempotent so it
is safe to call after a `clear_task_classes()` in tests.

OQ3 RATIFICATION (B2.8) — reasoning_budget_tokens=40000, blast_radius_limit=40.
Ratification basis: the B2.7 loop-closure e2e (test_loop_closure_e2e). That test exercises
the dispatch loop structurally but with a MOCKED reasoning client (≈6 director tokens across
3 planning calls) and a NO-OP developer worker (0 editor file writes), so its measured
consumption is non-representative of a real scaffold workload. The provisional values are
therefore CONFIRMED as conservative, real-workload-sized defaults rather than tightened to
the degenerate observation: a greenfield scaffold legitimately touches dozens of files (40
is a reasonable cap) and the director's per-task planning budget (40000 tokens) is ~the §S8
floor for the full loop. Live-model calibration (real token/file telemetry) tightens these
in B3 once non-mocked runs accrue. Values are RATIFIED, no longer provisional.
"""

from devharness.task_classes.base import TaskClassSpec
from devharness.task_classes.registry import TASK_CLASSES, register_task_class

NEW_PROJECT_SCAFFOLD = TaskClassSpec(
    name="new_project_scaffold",
    reasoning_budget_tokens=40_000,  # RATIFIED B2.8 (OQ3) — conservative default; live calibration tightens in B3
    tier_minimum="T2",  # spec rev 0.3.5 §S2 table
    dominant_gate_sensitivity="blast_radius",
    blast_radius_limit=40,  # RATIFIED B2.8 (OQ3) — greenfield scaffold file-touch cap
    allowed_cost_modes=["per_token"],  # write authority forces per-token (§S8)
)

# B3.1 — the four existing-repo BUILD classes (spec §S2). Budgets/blast-radius are PROVISIONAL
# (per the OQ3 follow-up: tightened by live-workload telemetry across B3); tier_minimum + dominant
# gate sensitivity follow the §S2 table. All force per-token (write authority, §S8).
FEATURE = TaskClassSpec(
    name="feature",
    # RATIFIED rev 0.3.66 (OQ3) as a conservative default per the B2.8 precedent: director token
    # spend is enforced in-memory (Inv 16) but not persisted as telemetry, so there is no realized
    # token evidence to tighten on; USD cost telemetry (rev 0.3.60) accrues the future basis.
    reasoning_budget_tokens=50_000,
    tier_minimum="T2",  # §S2
    dominant_gate_sensitivity="scope+verifier_attached",
    # RATIFIED rev 0.3.66 (OQ3/#M4) from realized telemetry: 60 feature tasks across 7 projects,
    # observed_max=14 distinct files, p95=11, median=4 — ratify.py's own ceil(max × 1.5) = 21
    # (action=tighten from the provisional 30). The first evidence-based cap in the harness.
    blast_radius_limit=21,
    allowed_cost_modes=["per_token"],
)
BUGFIX = TaskClassSpec(
    name="bugfix",
    reasoning_budget_tokens=30_000,  # PROVISIONAL (OQ3) — tight scope
    tier_minimum="T1",  # low-complexity write — the writer runs cheaper here (operator decision, rev 0.3.84)
    dominant_gate_sensitivity="scope+verifier_attached",
    blast_radius_limit=10,  # PROVISIONAL (OQ3) — a bugfix touches few files
    allowed_cost_modes=["per_token"],
)
REFACTOR = TaskClassSpec(
    name="refactor",
    reasoning_budget_tokens=60_000,  # PROVISIONAL (OQ3) — wider touch
    tier_minimum="T2",
    dominant_gate_sensitivity="scope+blast_radius+verifier_attached",
    blast_radius_limit=80,  # PROVISIONAL (OQ3) — refactors touch many files
    allowed_cost_modes=["per_token"],
)
DEPENDENCY_BUMP = TaskClassSpec(
    name="dependency_bump",
    reasoning_budget_tokens=20_000,  # PROVISIONAL (OQ3)
    tier_minimum="T1",  # nearly-mechanical write — the writer runs cheaper here (operator decision, rev 0.3.84)
    dominant_gate_sensitivity="blast_radius+verifier_attached",
    blast_radius_limit=200,  # PROVISIONAL (OQ3) — lockfile + many call sites
    allowed_cost_modes=["per_token"],
)

# B3.6 — the maintenance class (§S6/§S8): read-only, idle-paced, the FIRST class to permit
# flat-cost (Invariant 13 — flat is allowed only for maintenance/consolidation classes).
MAINTENANCE = TaskClassSpec(
    name="maintenance",
    reasoning_budget_tokens=10_000,  # PROVISIONAL — most maintenance is deterministic, no LLM
    tier_minimum="T0",  # deterministic floor
    dominant_gate_sensitivity="none",  # read-only; no writes
    blast_radius_limit=0,  # read-only: zero file writes permitted
    allowed_cost_modes=["per_token", "flat"],  # flat-cost permitted (§S8)
)

BUILTIN_TASK_CLASSES = [NEW_PROJECT_SCAFFOLD, FEATURE, BUGFIX, REFACTOR, DEPENDENCY_BUMP, MAINTENANCE]


def register_builtin_task_classes() -> None:
    for spec in BUILTIN_TASK_CLASSES:
        if spec.name not in TASK_CLASSES:
            register_task_class(spec)


register_builtin_task_classes()
