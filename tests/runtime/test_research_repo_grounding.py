"""Gap C: research grounds the synthesized spec in an EXISTING repo's structure.

When target_repo is set, ResearchRole runs a read-only explore pass over it and feeds the structural
summary (frameworks, test setup, layout) into the synthesis prompt, so the feature it proposes fits the
codebase. Structure only — never file contents. With no target_repo the prompt is the greenfield form.
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.roles.research import ResearchRole
from devharness.roles.synthesis import synthesis_prompt


class _Out:
    def __init__(self, output, is_error=False):
        self.output = output
        self.is_error = is_error


class _FakeParallax:
    """Records the synthesis prompt; stubs the interview calls."""
    def __init__(self, body_json):
        self.body_json = body_json
        self.complete_prompt = None

    async def elicit(self, *, task, context=None):
        # rev 0.4.11: payload-shaped per the server contract — bare prose is now an errored round
        return _Out('{"assumed_objective": "build X", "signal_level": "high", '
                    '"divergence_points": [{"question": "what is the scope?", "signal": "s"}]}')

    async def diverge(self, *, problem, context=None):
        return _Out("alt framing")

    async def complete(self, prompt):
        self.complete_prompt = prompt
        return _Out(self.body_json, is_error=False)


def _python_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "pyproject.toml").write_text('[project]\nname = "proj"\ndependencies = ["pytest"]\n')
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    run("add", "-A")
    run("commit", "-m", "init")
    return repo


def _valid_body():
    return json.dumps({
        "scope": "add X to the CLI", "non_goals": [], "interfaces": ["cli"],
        "success_criteria": ["X works"], "verification_plan": "unit tests",
    })


def test_research_grounds_spec_in_repo_structure(tmp_path):
    repo = _python_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    fake = _FakeParallax(_valid_body())
    role = ResearchRole.spawn(
        conn=conn, correlation_id="c-ext", parallax=fake, event_bus=EventBus(conn),
        target_repo=str(repo), answer_fn=lambda qid, qt: "ans", max_questions=1, now_millis=lambda: 7,
    )
    asyncio.run(role.run("propose a feature", "c-ext"))

    assert fake.complete_prompt is not None
    # grounded in the existing repo's actual structure
    assert "EXISTING repository" in fake.complete_prompt
    assert "pyproject.toml" in fake.complete_prompt       # detected manifest
    assert "pytest" in fake.complete_prompt               # detected test setup / framework


def test_research_without_target_repo_is_greenfield(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    fake = _FakeParallax(_valid_body())
    role = ResearchRole.spawn(
        conn=conn, correlation_id="c-green", parallax=fake, event_bus=EventBus(conn),
        answer_fn=lambda qid, qt: "ans", max_questions=1, now_millis=lambda: 7,
    )
    asyncio.run(role.run("build a thing", "c-green"))

    assert fake.complete_prompt is not None
    assert "EXISTING repository" not in fake.complete_prompt  # greenfield prompt unchanged


def test_synthesis_prompt_back_compat_without_summary():
    p = synthesis_prompt("idea", ["a1"])
    assert "EXISTING repository" not in p
    p2 = synthesis_prompt("idea", ["a1"], repo_summary="Top-level entries: src, tests")
    assert "EXISTING repository" in p2 and "src, tests" in p2
