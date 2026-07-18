"""rev 0.3.70: the first console-driven dependency_bump — end to end.

Live, the director-planned bump task carried empty class fields and the dispatch CRASHED in the
verifier (WinError 87 on the empty bump_command) with no terminal, so W re-crashed forever. This
drives the same shape through the real console dispatch: the class fields (except a preset benign
bump_command — the derived pip --dry-run would hit the network in CI) derive from the realized
diff, the verifier passes on the realized manifest change, and the task earns `completed` twice.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console.app import ConsoleApp
from devharness.mcp.base import CallResult
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.task_classes.builtin import register_builtin_task_classes

CID = "c-bump"


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


class _FakeParallax:
    async def verify(self, claim=None, context=""):
        return CallResult(output="Verdict: **supported** (confidence 1.0).",
                          cost_usd=0.0, usage=None, is_error=False)


def test_console_dependency_bump_derives_fields_and_completes(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "requirements.txt").write_text("packaging==24.0\n")
    (repo / "app.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")

    app = ConsoleApp(db_path=":memory:").connect()
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('spec-b','spec',1,'{}',?,100,1)", (CID,))
    app.conn.commit()
    app.writer.emit_sync("spec_signed", {"spec_id": "spec-b", "signer": "op",
                                         "signed_at_millis": 1}, CID)
    register_builtin_task_classes()

    async def _rq(*, prompt, options):
        yield _R()

    # bump_command preset (benign, no network); every OTHER class field left empty — the live shape
    app.director().plan(CID, spec_id="spec-b", tasks=[{
        "task_class": "dependency_bump",
        "description": "bump packaging from 24.0 to 25.0; behavior unchanged",
        "scope_boundary": ["requirements.txt"], "dependencies": [],
        "bump_command": "python -c pass",
    }], reasoning=MCPReasoningClient(query_fn=_rq))

    async def _noop(*, prompt, options):
        if False:
            yield None

    def write_hook(editor, shell, test_runner):
        editor.write_file("requirements.txt", "packaging==25.0\n", predicted_success=0.9)

    test_cmd = ["python", "-c",
                "import sys; sys.exit(0 if '25.0' in open('requirements.txt').read() else 1)"]
    terminal = app.developer(base_path=str(repo), test_command=test_cmd).dispatch(
        CID, parallax=_FakeParallax(),
        developer_kwargs={"base_path": str(repo), "query_fn": _noop, "write_hook": write_hook},
        snapshot=False,
    )
    assert terminal.outcome == "completed", terminal

    # the verifier ran with DERIVED fields: its outcome evidence names packaging 25.0
    row = app.conn.execute(
        "SELECT payload FROM events WHERE event_type='verifier_outcome' ORDER BY seq LIMIT 1"
    ).fetchone()
    evidence = json.loads(row[0]).get("evidence") or {}
    assert evidence.get("dependency_name") == "packaging"
    assert evidence.get("target_version") == "25.0"
    assert evidence.get("lockfile_axis") == "skipped: no lockfile in project"
