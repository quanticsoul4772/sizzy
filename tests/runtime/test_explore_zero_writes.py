"""B1.5: the explore module performs zero file writes — statically and at runtime."""

import ast
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.explore.runner import run

EXPLORE_DIR = Path(__file__).resolve().parents[2] / "runtime" / "devharness" / "explore"

_WRITE_MODE_CHARS = set("wax+")
_WRITE_ATTRS = {"write_text", "write_bytes"}
_WRITE_OS_FLAGS = {"O_WRONLY", "O_RDWR"}


class _WriteFinder(ast.NodeVisitor):
    def __init__(self):
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call):
        func = node.func
        # open(..., "w"/"a"/"x"/"+") — positional mode or mode= kwarg
        is_open = (isinstance(func, ast.Name) and func.id == "open") or (
            isinstance(func, ast.Attribute) and func.attr == "open"
        )
        if is_open:
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if isinstance(mode, str) and (set(mode) & _WRITE_MODE_CHARS):
                self.violations.append(f"open(mode={mode!r}) at line {node.lineno}")
        # Path.write_text / write_bytes
        if isinstance(func, ast.Attribute) and func.attr in _WRITE_ATTRS:
            self.violations.append(f"{func.attr}() at line {node.lineno}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in _WRITE_OS_FLAGS:
            self.violations.append(f"os.{node.attr} at line {node.lineno}")
        self.generic_visit(node)


def test_static_ast_scan_finds_no_write_ops():
    violations = {}
    for py in EXPLORE_DIR.rglob("*.py"):
        finder = _WriteFinder()
        finder.visit(ast.parse(py.read_text(encoding="utf-8")))
        if finder.violations:
            violations[py.name] = finder.violations
    assert violations == {}, violations


def _checksums(root: Path) -> dict:
    sums = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            sums[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sums


def test_runtime_repo_unmodified(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["fastapi"]\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x(): pass\n")

    before = _checksums(tmp_path)
    run(str(tmp_path), "corr-1")
    after = _checksums(tmp_path)
    assert before == after
