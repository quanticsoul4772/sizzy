"""rev 0.4.26: advisory-lite LIVE validation — operator-driven, spends real money.

Gated like the SC-3 real-launcher runs: set ``DEVHARNESS_RUN_ADVISORY_LIVE=1`` to run. The test
drives the hermetic feature build (`faultinjection/hermetic.py` — a real temp git repo, in-memory
store, seeded signed spec + plan) through ``ConsoleDeveloper.dispatch`` with a real
``ParallaxClient`` whose launch spec points at the bundled advisory server. One dispatch exercises
the full relay → stdio-boot → nested-SDK loop for BOTH the verifier and the fresh-context reviewer
(and the non-goals gate); a genuinely COMPLETED terminal is the proof that the advisory verdicts
parse through the whole done-earned-twice chain.

Windows residual (documented): an abrupt CLI kill can orphan the spawned advisory server process —
the existing process-hygiene observability (resource snapshots / process counts) applies.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

_OPT_IN = os.environ.get("DEVHARNESS_RUN_ADVISORY_LIVE") == "1"

_ADVISORY_SPEC = {"command": sys.executable, "args": ["-m", "devharness.advisory", "--tools", "parallax"]}


@pytest.mark.skipif(not _OPT_IN, reason="advisory-lite live run is operator-driven (set DEVHARNESS_RUN_ADVISORY_LIVE=1; spends real money)")
def test_advisory_lite_completes_a_hermetic_feature_build(monkeypatch):
    # the drivers' posture (rev 0.4.6): a stray machine-level ANTHROPIC_API_KEY kills the CLI at
    # launch (exit 1) — every driver pops it at startup; this live test must too, or the relay
    # session dies before the advisory server is ever spawned (live-hit on the first run)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from devharness.faultinjection.hermetic import TEST_CMD, clean_write_hook, hermetic_build, noop_query
    from devharness.mcp.parallax import ParallaxClient

    build = hermetic_build()
    try:
        terminal = build.developer(test_command=TEST_CMD).dispatch(
            build.correlation_id,
            parallax=ParallaxClient(mcp_servers={"parallax": _ADVISORY_SPEC}),
            developer_kwargs={
                "base_path": str(build.repo),
                "base_ref": "feature-base",
                "query_fn": noop_query(),
                "write_hook": clean_write_hook,
            },
            snapshot=False,
        )
        assert terminal.outcome == "completed", (
            f"advisory-lite verdicts did not carry the build to completion: "
            f"{terminal.outcome} ({terminal.reason})"
        )
    finally:
        build.cleanup()


def test_advisory_live_module_is_opt_in():
    # the always-running guard (the SC-3 pattern): the launch spec is real and gated, never mocked
    assert _ADVISORY_SPEC["args"][-2:] == ["--tools", "parallax"]
