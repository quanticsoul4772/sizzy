"""#H3: a real LLM backs the retro residue path; the dormant §S7 LLM branch now produces candidates.

make_llm_fn(client) turns an MCP client into the engine's sync llm_fn, parsing the model reply
strictly: a malformed reply from a SUCCESSFUL call -> [] (best-effort), but a TRANSPORT failure or
errored result raises LLMUnavailable (rev 0.3.57 — swallowing it to [] let a down SDK permanently
consume every terminal in a store as "analyzed, nothing found"). End-to-end: a benign residue context
(no T0 match, non-hostile) routes to the LLM and the returned candidates are emitted with
source='llm'; a core-gate gate-change is dropped by the downstream filter.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.mcp.base import CallResult
from devharness.retro.base import RetroContext
from devharness.retro.engine import RetroEngine
from devharness.retro.gate_change_validator import CORE_GATES
from devharness.retro.llm_client import LLMUnavailable, make_llm_fn


class _FakeClient:
    def __init__(self, output):
        self._output = output
        self.prompts = []

    async def complete(self, prompt):
        self.prompts.append(prompt)
        return CallResult(output=self._output, cost_usd=0.0, usage=None, is_error=False)


class _RaisingClient:
    async def complete(self, prompt):
        raise RuntimeError("transport down")


class _Bus:
    def __init__(self):
        self.events = []

    def emit_sync(self, event_type, payload, correlation_id=None):
        self.events.append((event_type, payload))


def _ctx():
    # a benign completed terminal: no gate-deny/verifier-fail -> no T0 match; non-hostile text -> LLM
    return RetroContext(
        terminal_outcome_event={"task_id": "t", "outcome": "completed"},
        preceding_events=[{"event_id": "e1", "event_type": "task_started", "payload": {}}],
        calibration_snapshot={}, source_task_id="t", correlation_id="c",
        verifier_outcome=None, reviewer_certification=None,
    )


_ANTIBODY = '[{"kind":"antibody_candidate","signature_name":"novel_x","pattern_text":"watch for X","evidence_event_ids":[]}]'


def test_parses_a_clean_json_array():
    fn = make_llm_fn(_FakeClient(_ANTIBODY))
    out = fn("sys", _ctx(), "T1")
    assert len(out) == 1 and out[0]["kind"] == "antibody_candidate" and out[0]["signature_name"] == "novel_x"


def test_extracts_json_wrapped_in_prose():
    fn = make_llm_fn(_FakeClient('Here are the candidates:\n' + _ANTIBODY + '\nThanks.'))
    assert len(fn("sys", _ctx(), "T1")) == 1


def test_malformed_reply_yields_no_candidates():
    for bad in ("not json at all", "", "{not an array}", "[oops"):
        assert make_llm_fn(_FakeClient(bad))("sys", _ctx(), "T1") == []


def test_transport_failure_raises_llm_unavailable():
    # the analysis never happened — [] here would let the scheduler consume the terminal forever
    with pytest.raises(LLMUnavailable):
        make_llm_fn(_RaisingClient())("sys", _ctx(), "T1")


def test_errored_result_raises_llm_unavailable():
    class _ErroredClient:
        async def complete(self, prompt):
            return CallResult(output="", cost_usd=0.0, usage=None, is_error=True)

    with pytest.raises(LLMUnavailable):
        make_llm_fn(_ErroredClient())("sys", _ctx(), "T1")


def test_engine_emits_llm_candidates_end_to_end():
    bus = _Bus()
    RetroEngine(llm_fn=make_llm_fn(_FakeClient(_ANTIBODY))).analyze(_ctx(), bus)
    emitted = [et for et, _ in bus.events]
    assert "antibody_candidate" in emitted
    payload = next(p for et, p in bus.events if et == "antibody_candidate")
    assert payload["source"] == "llm" and payload["signature_name"] == "novel_x"


def test_core_gate_gate_change_is_dropped_downstream():
    core = sorted(CORE_GATES)[0]
    reply = f'[{{"kind":"gate_change_candidate","signature_name":"sneaky","target_gate":"{core}","change_kind":"weaken","change_details":{{}},"evidence_event_ids":[]}}]'
    bus = _Bus()
    RetroEngine(llm_fn=make_llm_fn(_FakeClient(reply))).analyze(_ctx(), bus)
    # the core-gate proposal must never reach the queue
    assert all(et != "gate_change_candidate" for et, _ in bus.events)
