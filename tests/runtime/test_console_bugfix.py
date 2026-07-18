"""rev 0.3.73: the first console-driven bugfix — end to end.

Live (an HTML-converter XSS): a director-planned bugfix carried regression_test_ref='' and the verifier
crashed with KeyError (no terminal, W re-crash loop). This drives the same shape through the real
console dispatch: the ref derives from the realized diff (the new test file), the baseline overlays
that test so 'bug present at baseline' is genuine, and the task earns `completed` twice.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console.app import ConsoleApp
from devharness.mcp.base import CallResult
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.task_classes.builtin import register_builtin_task_classes

CID = "c-bugfix"


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


class _FakeParallax:
    async def verify(self, claim=None, context=""):
        return CallResult(output="Verdict: **supported** (confidence 1.0).",
                          cost_usd=0.0, usage=None, is_error=False)


def test_console_bugfix_derives_ref_and_completes(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    # the bug: escape() forgets the double-quote
    (repo / "app.py").write_text(
        'def escape(s):\n    return s.replace("&", "&amp;")\n')
    run("add", "-A")
    run("commit", "-q", "-m", "base (buggy)")

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

    # a director-planned bugfix — NO regression_test_ref (the live shape that crashed)
    app.director().plan(CID, spec_id="spec-b", tasks=[{
        "task_class": "bugfix",
        "description": "escape() must also escape the double-quote to &quot;",
        "scope_boundary": ["app.py", "tests/test_app.py"], "dependencies": [],
    }], reasoning=MCPReasoningClient(query_fn=_rq))

    async def _noop(*, prompt, options):
        if False:
            yield None

    def write_hook(editor, shell, test_runner):
        # the fix
        editor.write_file("app.py",
                          'def escape(s):\n    return s.replace("&", "&amp;").replace(chr(34), "&quot;")\n',
                          predicted_success=0.9)
        # the NEW regression test — fails against the buggy baseline, passes after the fix
        editor.write_file("tests/test_app.py",
                          'from app import escape\n'
                          'def test_quote_escaped():\n    assert escape(chr(34)) == "&quot;"\n',
                          predicted_success=0.9)

    # the suite command the verifier runs (test_suite axis)
    test_cmd = ["python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]
    terminal = app.developer(base_path=str(repo), test_command=test_cmd).dispatch(
        CID, parallax=_FakeParallax(),
        developer_kwargs={"base_path": str(repo), "query_fn": _noop, "write_hook": write_hook},
        snapshot=False,
    )
    assert terminal.outcome == "completed", terminal

    # the verifier ran the DERIVED ref against an OVERLAID baseline — the bug was genuinely present
    import json
    row = app.conn.execute(
        "SELECT payload FROM events WHERE event_type='verifier_outcome' "
        "AND json_extract(payload,'$.verifier')='bugfix_regression' ORDER BY seq LIMIT 1").fetchone()
    ev = json.loads(row[0]).get("evidence") or {}
    assert ev.get("baseline_rc") not in (0, None)  # test failed at baseline (bug present, not vacuous)
    assert ev.get("baseline_overlay") == ["tests/test_app.py"]
