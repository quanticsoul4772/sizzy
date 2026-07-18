"""B4.5: CommitIdentity resolver — default + per-upstream env override + graceful fallback."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.oss.commit_identity import DEFAULT_OSS_COMMIT_IDENTITY, get_commit_identity

REPO = "octo/widget"


def test_default_identity_shape():
    d = DEFAULT_OSS_COMMIT_IDENTITY
    assert d.identity_name == "devharness-oss-bot"
    assert d.identity_email == "oss@devharness.local"
    assert d.assigned_by == "default"


def test_unconfigured_falls_back_to_default():
    assert get_commit_identity(REPO, "feature") == DEFAULT_OSS_COMMIT_IDENTITY


def test_per_upstream_override(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_COMMIT_IDENTITIES",
                       json.dumps({REPO: {"name": "widget-bot", "email": "bot@octo.example"}}))
    ident = get_commit_identity(REPO, "feature")
    assert ident.identity_name == "widget-bot" and ident.identity_email == "bot@octo.example"
    assert ident.assigned_by == "env_override"
    # an unconfigured upstream still gets the default
    assert get_commit_identity("other/repo", "feature") == DEFAULT_OSS_COMMIT_IDENTITY


def test_malformed_env_falls_back(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_COMMIT_IDENTITIES", "not json")
    assert get_commit_identity(REPO, "feature") == DEFAULT_OSS_COMMIT_IDENTITY


def test_incomplete_entry_falls_back(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_COMMIT_IDENTITIES", json.dumps({REPO: {"name": "x"}}))  # no email
    assert get_commit_identity(REPO, "feature") == DEFAULT_OSS_COMMIT_IDENTITY
