"""Track 2: oss/publish.py pushes the fork-branch + opens a PR via the GitHub API, emits oss_pr_opened.

The token is never logged; a push failure scrubs it from the error; a cross-repo fork PR prefixes the head
with the fork owner. The real git push + GitHub API are mocked here (the live end-to-end is operator-driven).
"""

import io
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.oss import publish
from devharness.oss.publish import PublishError, publish_pull_request
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _bus():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    reg = ProjectionRegistry()
    register_handlers(reg)
    return conn, EventBus(conn, reg)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_push(monkeypatch):
    monkeypatch.setattr(publish.subprocess, "run",
                        lambda a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr=""))


def _args(**over):
    base = dict(worktree_path="/wt", fork_branch="devharness-oss/t1", push_repo="o/r", pr_repo="o/r",
               base_branch="main", fork_owner="o", title="t", body="b", oss_task_id="t1",
               upstream_repo="o/r", correlation_id="c", token="ghp_SECRETxyz")
    base.update(over)
    return base


def test_publish_pushes_and_opens_pr(monkeypatch):
    conn, bus = _bus()
    pushed = {}

    def fake_run(args, **k):
        pushed["args"] = args
        pushed["env"] = k.get("env", {})
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(publish.subprocess, "run", fake_run)

    def fake_urlopen(req, **k):
        body = json.loads(req.data.decode())
        assert body["head"] == "devharness-oss/t1" and body["base"] == "main"
        return _Resp(json.dumps({"html_url": "https://github.com/o/r/pull/7", "number": 7}).encode())
    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)

    r = publish_pull_request(event_bus=bus, now_millis=lambda: 5, **_args())
    assert r == {"pr_url": "https://github.com/o/r/pull/7", "pr_number": 7, "fork_branch": "devharness-oss/t1"}
    # F5: token is NOT in argv (bare URL + credential helper referencing the env var by name); it's in env
    assert "https://github.com/o/r.git" in pushed["args"]
    assert not any("ghp_SECRETxyz" in str(a) for a in pushed["args"]), "token leaked into git argv"
    assert any("credential.helper=" in str(a) for a in pushed["args"])
    assert pushed["env"].get("GIT_PUSH_TOKEN") == "ghp_SECRETxyz"
    assert pushed["args"][-1] == "devharness-oss/t1:devharness-oss/t1"
    row = conn.execute("SELECT payload FROM events WHERE event_type='oss_pr_opened'").fetchone()
    assert row and json.loads(row[0])["pr_url"] == "https://github.com/o/r/pull/7"


def test_cross_repo_head_prefixes_fork_owner(monkeypatch):
    conn, bus = _bus()
    _ok_push(monkeypatch)
    seen = {}

    def fake_urlopen(req, **k):
        seen["head"] = json.loads(req.data.decode())["head"]
        return _Resp(json.dumps({"html_url": "u", "number": 1}).encode())
    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)

    publish_pull_request(event_bus=bus, **_args(push_repo="bot/r", pr_repo="up/r", fork_owner="bot"))
    assert seen["head"] == "bot:b" or seen["head"].endswith(":devharness-oss/t1")


def test_push_failure_raises_and_scrubs_token(monkeypatch):
    conn, bus = _bus()
    monkeypatch.setattr(publish.subprocess, "run", lambda a, **k: types.SimpleNamespace(
        returncode=1, stdout="", stderr="error: remote rejected (saw ghp_SECRETxyz in transit)"))
    with pytest.raises(PublishError) as e:
        publish_pull_request(event_bus=bus, **_args())
    assert "ghp_SECRETxyz" not in str(e.value) and "***" in str(e.value)


def test_missing_token_raises(monkeypatch):
    conn, bus = _bus()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(PublishError):
        publish_pull_request(event_bus=bus, **_args(token=None))
