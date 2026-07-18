"""B1.7: read-only enforcement — B1 roles have zero write tools, the explore module
performs zero writes, and no write-lock-taking path exists yet."""

import ast
import hashlib
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

from devharness.call_class import classify
from devharness.explore.runner import run
from devharness.migrate import migrate
from devharness.projections.handlers import HANDLERS
from devharness.roles.base import AgentRole
from devharness.roles.director import DirectorRole, tool_inventory_for as director_inventory
from devharness.roles.research import ResearchRole, tool_inventory_for as research_inventory

EXPLORE_DIR = ROOT / "runtime" / "devharness" / "explore"
_WRITE_MODE_CHARS = set("wax+")
_WRITE_ATTRS = {"write_text", "write_bytes"}
_WRITE_OS_FLAGS = {"O_WRONLY", "O_RDWR"}


def _no_write_tools(inventory):
    assert not any(t in inventory for t in ("Edit", "Write", "Bash", "NotebookEdit"))
    assert all(classify(tool) != "mutation" for tool in inventory)


def test_research_role_zero_write_tools():
    _no_write_tools(research_inventory(ResearchRole.ALLOWED_MCP_SERVERS))


def test_director_role_zero_write_tools():
    _no_write_tools(director_inventory(DirectorRole.ALLOWED_MCP_SERVERS))


def test_explore_module_static_no_write_ops():
    class _Finder(ast.NodeVisitor):
        def __init__(self):
            self.bad = []

        def visit_Call(self, node):
            f = node.func
            is_open = (isinstance(f, ast.Name) and f.id == "open") or (isinstance(f, ast.Attribute) and f.attr == "open")
            if is_open:
                mode = None
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                if isinstance(mode, str) and (set(mode) & _WRITE_MODE_CHARS):
                    self.bad.append((node.lineno, mode))
            if isinstance(f, ast.Attribute) and f.attr in _WRITE_ATTRS:
                self.bad.append((node.lineno, f.attr))
            self.generic_visit(node)

        def visit_Attribute(self, node):
            if node.attr in _WRITE_OS_FLAGS:
                self.bad.append((node.lineno, node.attr))
            self.generic_visit(node)

    offenders = {}
    for py in EXPLORE_DIR.rglob("*.py"):
        finder = _Finder()
        finder.visit(ast.parse(py.read_text(encoding="utf-8")))
        if finder.bad:
            offenders[py.name] = finder.bad
    assert offenders == {}, offenders


def test_explore_runtime_leaves_repo_unmodified(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["pytest"]\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1\n")

    def checksums():
        return {
            str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(tmp_path.rglob("*")) if p.is_file()
        }

    before = checksums()
    run(str(tmp_path), "corr-1")
    assert checksums() == before


def test_only_the_developer_holds_write_authority():
    # as of B2.3 the developer role exists and is the single writer; the advisory
    # roles (research, director) remain read-only.
    importlib.import_module("devharness.roles.developer")  # imports cleanly now
    subclasses = {c.__name__ for c in AgentRole.__subclasses__()}
    assert "DeveloperRole" in subclasses
    assert subclasses <= {"ResearchRole", "DirectorRole", "DeveloperRole", "ReviewerRole"}
    _no_write_tools(research_inventory(ResearchRole.ALLOWED_MCP_SERVERS))
    _no_write_tools(director_inventory(DirectorRole.ALLOWED_MCP_SERVERS))
    # the lock projection handlers exist (B2.0); only the developer claims the lock (B2.3)
    assert "write_lock_acquired" in HANDLERS and "write_lock_released" in HANDLERS


def test_proj_lock_unclaimed_on_fresh_db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 0
