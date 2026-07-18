"""Worker self-correction (the 'follow the stated location' work): the worker prompt carries a binding
location directive, the spec_claim it's judged against, and — on a re-dispatch — the prior verifier
refutation, so a deviated attempt self-corrects without a hand-edited description."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.roles.developer import DeveloperRole

CID = "corr-fb"
TID = f"{CID}-t0"


def _dev(conn):
    return DeveloperRole.spawn(conn=conn, correlation_id=CID, event_bus=EventBus(conn), base_path=".")


def _task(spec_claim=""):
    return PlannedTask(
        task_id=TID, task_class="feature", description="register the routes in app::build_app",
        scope_boundary=["src/**"], dependencies=[], correlation_id=CID, spec_claim=spec_claim,
    )


def _seed_rejection(conn, output):
    EventBus(conn).emit_sync("verifier_outcome", {
        "task_id": TID, "verifier": "feature_spec_claim", "passed": False,
        "detail": "spec_claim axis failed: parallax.verify did not confirm the claim",
        "evidence": {"parallax_verify": {"tool": "parallax.verify", "output": output}},
    }, correlation_id=CID)


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_first_attempt_has_directive_no_feedback():
    dev = _dev(_db())
    p = dev._worker_prompt(_task(), CID)
    assert "PRIOR attempt" not in p           # no rejection yet
    assert "OUTER bound" in p                  # the binding-location directive is present


def test_prompt_renders_the_effective_scope_union():
    # rev 0.3.71: the widener's union governed both ENFORCEMENT layers but the prompt still told
    # the worker the narrow plan globs — so it obeyed and never touched the widened files (live:
    # a dependency-metadata-scoped bump could not update the repo's version-pin test). The prompt
    # now renders the union and names the widened files explicitly.
    dev = _dev(_db())
    dev._effective_scope = ["src/**", "tests/test_cli.py"]  # what _run_worker sets post-widening
    p = dev._worker_prompt(_task(), CID)
    assert "tests/test_cli.py" in p
    assert "must ALSO be updated" in p
    assert "['src/**', 'tests/test_cli.py']" in p  # the scope line carries the union, not the plan globs


def test_prompt_without_widening_is_unchanged():
    dev = _dev(_db())
    p = dev._worker_prompt(_task(), CID)  # _effective_scope is None before _run_worker
    assert "must ALSO be updated" not in p
    assert "['src/**']" in p


def test_prior_rejection_json_findings_fed_back():
    conn = _db()
    _seed_rejection(conn, json.dumps({"verdict": "refuted",
                                      "findings": ["routes registered in main.rs, not app::build_app"]}))
    dev = _dev(conn)
    assert "routes registered in main.rs" in dev._prior_rejection(TID)
    p = dev._worker_prompt(_task(), CID)
    assert "PRIOR attempt at this task was REJECTED" in p and "main.rs" in p


def test_prior_rejection_prose_string_fed_back():
    conn = _db()
    _seed_rejection(conn, "the diff wires auth in main.rs instead of build_app")
    dev = _dev(conn)
    assert "main.rs" in dev._prior_rejection(TID)
    assert "main.rs" in dev._worker_prompt(_task(), CID)


def test_spec_claim_surfaced_when_distinct_from_description():
    dev = _dev(_db())
    p = dev._worker_prompt(_task(spec_claim="The auth routes are registered inside app::build_app"), CID)
    assert "verified against this exact claim" in p and "inside app::build_app" in p


def test_passing_outcome_is_not_treated_as_a_rejection():
    conn = _db()
    EventBus(conn).emit_sync("verifier_outcome", {
        "task_id": TID, "verifier": "feature_spec_claim", "passed": True, "detail": "", "evidence": {},
    }, correlation_id=CID)
    assert _dev(conn)._prior_rejection(TID) == ""
