"""B2.1: Invariant 13 — `cost_mode ==` comparisons are confined to the two
whitelisted modules (cost_mode.py, cost_router.py)."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

DEVHARNESS = ROOT / "runtime" / "devharness"
WHITELIST = {"cost_mode.py", "cost_router.py"}


def _references_cost_mode(node) -> bool:
    return (isinstance(node, ast.Name) and node.id == "cost_mode") or (
        isinstance(node, ast.Attribute) and node.attr == "cost_mode"
    )


def cost_mode_eq_files() -> set[str]:
    """Files under runtime/devharness/ that contain a `cost_mode ==`/`== cost_mode` comparison."""
    offenders: set[str] = set()
    for py in DEVHARNESS.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare) and any(isinstance(op, ast.Eq) for op in node.ops):
                operands = [node.left, *node.comparators]
                if any(_references_cost_mode(o) for o in operands):
                    offenders.add(py.name)
    return offenders


def test_cost_mode_equality_confined_to_two_modules():
    files = cost_mode_eq_files()
    assert files <= WHITELIST, f"cost_mode == comparison outside the whitelist: {files - WHITELIST}"


def test_the_comparison_actually_exists():
    # guard against a vacuous pass: cost_mode.py does carry the equality comparisons
    assert "cost_mode.py" in cost_mode_eq_files()
