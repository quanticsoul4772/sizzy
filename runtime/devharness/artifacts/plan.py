"""Plan-artifact schema (B1.4).

The director's output: a decomposition of a signed spec into scoped tasks. Each
task carries its scope boundary (the globs it may touch) and dependencies. The
plan is consumed by the developer role in B2; the director never dispatches.
"""

import msgspec

from devharness.artifacts.registry import register_artifact_schema


class OssEnvelope(msgspec.Struct, frozen=True, kw_only=True):
    """B4.0: the external-repo envelope carried by an `is_oss=True` BUILD task (§S5).

    An OSS contribution is a feature/bugfix/refactor/dependency_bump against an external repo —
    not a standalone class (OQ-B4-2). This struct holds the contribution's upstream context; the
    four §S5 gates layer onto the BUILD class's gate profile when `is_oss=True`.
    """
    upstream_repo: str
    license_spdx: str
    requester_id: str
    target_branch: str
    schema_version: int = 1


class PlannedTask(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    task_class: str
    description: str
    scope_boundary: list[str]  # file/path globs the task may touch
    dependencies: list[str]  # other task_ids that must complete first
    correlation_id: str
    verifier_ref: str | None = None  # the attached verification plan (set in B2.2)
    spec_claim: str = ""  # B3.2 additive: the feature's spec claim (parallax.verify target)
    regression_test_ref: str = ""  # B3.3 additive: the bugfix's demonstrating regression test
    # B3.5 additive: dependency_bump descriptors (the dependency_resolves verifier reads these)
    dependency_name: str = ""
    target_version: str = ""
    bump_command: str = ""
    manifest_path: str = ""
    lockfile_path: str = ""
    # B4.0 additive: OSS-flagged composition (OQ-B4-2). is_oss layers the four §S5 gates onto the
    # BUILD class's gate profile; oss_envelope carries the upstream context (None for non-OSS tasks).
    is_oss: bool = False
    oss_envelope: OssEnvelope | None = None
    schema_version: int = 1


class PlanArtifact(msgspec.Struct, frozen=True, kw_only=True):
    plan_id: str
    spec_artifact_id: str  # the signed spec this plans
    tasks: list[PlannedTask]  # may be empty for a no-work-needed plan
    correlation_id: str
    created_at_millis: int
    schema_version: int = 1


register_artifact_schema("plan", PlanArtifact)
