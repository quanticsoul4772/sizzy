"""Non-goals guard: a planned task may not pursue the signed spec's explicit non-goals.

The deterministic heuristic catches blatant pursuits (every salient word of a non-goal present in the
task text); the injectable conformance_check is the semantic path (a reasoning/parallax-backed checker
the director can wire) for subtler cases. The director aborts a denied task before dispatch.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.non_goals_guard import NonGoalsGuard, keyword_coverage_violation


def test_no_non_goals_is_a_pass():
    assert isinstance(NonGoalsGuard().check({"task_description": "anything"}), GateOk)


def test_heuristic_denies_a_blatant_non_goal_pursuit():
    result = NonGoalsGuard().check({
        "non_goals": ["a graphical user interface"],
        "task_description": "add a graphical user interface panel to the tool",
        "task_scope": ["ui/panel.py"],
    })
    assert isinstance(result, GateDeny)
    assert result.evidence["violated_non_goal"] == "a graphical user interface"


def test_heuristic_allows_an_in_scope_task():
    result = NonGoalsGuard().check({
        "non_goals": ["a graphical user interface"],
        "task_description": "add a --compact CLI flag",
        "task_scope": ["jqlite/cli.py"],
    })
    assert isinstance(result, GateOk)


def test_heuristic_requires_full_keyword_coverage_no_false_positive():
    # sharing one generic word with a non-goal must NOT flag (conservative — avoids blocking real work)
    assert keyword_coverage_violation("add a json parser", [], ["a graphical user interface"]) is None
    # every salient word present -> flagged
    assert keyword_coverage_violation(
        "build the graphical interface for the user", [], ["graphical user interface"]) == "graphical user interface"


def test_injected_semantic_checker_supersedes_the_heuristic():
    g = NonGoalsGuard()
    # a semantic checker that flags the rich-dependency case the heuristic would miss
    flag_deps = lambda desc, scope, ngs: ngs[0] if "rich" in desc else None
    denied = g.check({"non_goals": ["third-party dependencies (stdlib only)"],
                      "task_description": "add an optional rich --color extra", "conformance_check": flag_deps})
    assert isinstance(denied, GateDeny)
    # a checker that clears it -> pass, even if the heuristic might have matched
    ok = g.check({"non_goals": ["graphical user interface"],
                  "task_description": "graphical user interface", "conformance_check": lambda d, s, n: None})
    assert isinstance(ok, GateOk)


def test_heuristic_does_not_flag_an_in_scope_criterion_feature():
    # #3b: a feature that fully implements a success-criterion ("streaming output …") is in-scope even when
    # its salient words also fully cover a similarly-worded non-goal — the criteria-aware fallback clears it.
    v = keyword_coverage_violation(
        "implement streaming output for finite JSON arrays", [],
        ["streaming output"],                          # non-goal (its salient words are covered by the task)
        ["streaming output for finite JSON arrays"])   # success-criterion (also fully covered → in-scope)
    assert v is None


def test_heuristic_still_flags_a_genuine_non_goal_with_criteria_present():
    # a real non-goal the task does NOT match as a criterion is still flagged even with criteria supplied
    v = keyword_coverage_violation(
        "add a third-party color dependency", ["pyproject.toml"],
        ["third-party dependency"],
        ["JSON array output"])   # a criterion the task does not cover -> no clear
    assert v == "third-party dependency"


def test_gate_fallback_is_criteria_aware_via_context():
    # the gate threads success_criteria into the deterministic fallback (no conformance_check supplied)
    ok = NonGoalsGuard().check({
        "non_goals": ["streaming output"], "task_description": "implement streaming output for finite JSON",
        "task_scope": [], "success_criteria": ["streaming output for finite JSON"]})
    assert isinstance(ok, GateOk)
    deny = NonGoalsGuard().check({
        "non_goals": ["streaming output"], "task_description": "implement streaming output for finite JSON",
        "task_scope": [], "success_criteria": ["unrelated criterion"]})
    assert isinstance(deny, GateDeny)
