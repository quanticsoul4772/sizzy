"""B5.0: RetroContext + RetroResult structs."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.retro.base import RetroContext, RetroResult


def test_context_frozen_kw_only():
    c = RetroContext(terminal_outcome_event={"task_id": "t1", "outcome": "completed"}, preceding_events=[],
                     calibration_snapshot={}, source_task_id="t1", correlation_id="c")
    assert c.source_task_id == "t1" and c.verifier_outcome is None and c.reviewer_certification is None
    with pytest.raises(AttributeError):
        c.source_task_id = "t2"
    with pytest.raises(TypeError):
        RetroContext({"x": 1}, [], {}, "t1", "c")  # positional rejected (kw_only)


def test_context_optional_fields():
    c = RetroContext(terminal_outcome_event={}, preceding_events=[{"event_type": "task_started"}],
                     calibration_snapshot={"brier": 0.1}, source_task_id="t1", correlation_id="c",
                     verifier_outcome={"outcome": "pass"}, reviewer_certification={"verdict": "certified"})
    assert c.verifier_outcome["outcome"] == "pass" and c.calibration_snapshot["brier"] == 0.1


def test_result_roundtrip():
    r = RetroResult(candidates_emitted=["cand-1"], summary="ok")
    assert msgspec.convert(msgspec.to_builtins(r), RetroResult) == r
