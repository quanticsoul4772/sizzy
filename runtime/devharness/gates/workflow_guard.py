"""workflow_guard gate (§S5 OSS fear-map; real body B4.2).

Blocks writes to CI/CD workflow files (GitHub Actions + other major CI systems). An OSS
contribution must not silently alter the upstream's automation. Override: an approved-issue
`allow_workflow_edit` (carried as `workflow_guard_override=True` in the context, audited in
gate_fired). GitHub-specific by construction (spec Assumptions); the pattern set is extensible.
"""

from fnmatch import fnmatch

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate

# CI/CD workflow paths across major systems (extensible)
WORKFLOW_PATH_PATTERNS = (
    ".github/workflows/*", ".github/workflows/**",
    ".github/actions/*", ".github/actions/**",
    ".gitlab-ci.yml",
    ".buildkite/*", ".buildkite/**",
    ".circleci/config.yml", ".circleci/*", ".circleci/**",
)


def _matches_workflow(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(fnmatch(p, pat) for pat in WORKFLOW_PATH_PATTERNS)


class WorkflowGuard(Gate):
    name = "workflow_guard"

    def check(self, context: dict):
        matched = [p for p in context.get("touched_paths", []) if _matches_workflow(p)]
        if not matched:
            return GateOk()
        if context.get("workflow_guard_override") is True:
            return GateOk(reason="workflow_modified_with_override")
        return GateDeny(
            reason=f"workflow_modified: {len(matched)} path(s) touch CI/CD workflow files",
            purpose="OSS contributions must not silently alter the upstream's CI/CD automation (§S5 workflow_guard)",
            fix="Remove the workflow change, or attach an approved-issue allow_workflow_edit override",
            evidence={"matched_paths": matched},
        )


register_gate("workflow_guard", WorkflowGuard())
