"""B3.6: Inv 13 still holds with the maintenance class permitting flat-cost — the
`cost_mode ==` comparisons stay confined to cost_mode.py and cost_router.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from test_invariant_13 import WHITELIST, cost_mode_eq_files

from devharness.cost_router import requires_per_token
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.registry import clear_task_classes


def test_confinement_holds_after_maintenance():
    files = cost_mode_eq_files()
    assert files <= WHITELIST, f"cost_mode == comparison outside the whitelist: {files - WHITELIST}"
    assert "cost_mode.py" in files  # non-vacuous


def test_maintenance_is_the_only_flat_class():
    clear_task_classes()
    register_builtin_task_classes()
    try:
        assert requires_per_token("maintenance") is False
        for write_class in ("new_project_scaffold", "feature", "bugfix", "refactor", "dependency_bump"):
            assert requires_per_token(write_class) is True
    finally:
        clear_task_classes()
