"""B4.0: PlannedTask gains is_oss (default False) + oss_envelope (default None), additive."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import OssEnvelope, PlannedTask


def test_oss_fields_default():
    t = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=[], dependencies=[], correlation_id="c")
    assert t.is_oss is False and t.oss_envelope is None


def test_oss_fields_set():
    env = OssEnvelope(upstream_repo="octo/widget", license_spdx="MIT", requester_id="r1", target_branch="main")
    t = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=[], dependencies=[],
                    correlation_id="c", verifier_ref="feature_spec_claim", is_oss=True, oss_envelope=env)
    assert t.is_oss is True and t.oss_envelope.upstream_repo == "octo/widget"


def test_pre_b4_construction_unaffected():
    # a pre-B4 construction (no is_oss/oss_envelope) still builds, with B3 fields intact
    t = PlannedTask(task_id="t1", task_class="dependency_bump", description="d", scope_boundary=["**"], dependencies=[],
                    correlation_id="c", verifier_ref="dependency_resolves", dependency_name="requests", target_version="2.31.0")
    assert t.is_oss is False and t.oss_envelope is None and t.dependency_name == "requests"
