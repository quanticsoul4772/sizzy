"""B4.1: maintainer verification — env-config default verifier + seeded test verifier."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.oss.maintainer import DefaultMaintainerVerifier, TestMaintainerVerifier


def test_default_verifier_from_injected_map():
    v = DefaultMaintainerVerifier({"octo/widget": ["alice", "bob"]})
    assert v.verify("octo/widget", "alice") is True
    assert v.verify("octo/widget", "mallory") is False  # not a maintainer
    assert v.verify("octo/other", "alice") is False  # not a maintainer of that repo


def test_default_verifier_from_env(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_MAINTAINERS", json.dumps({"octo/widget": ["carol"]}))
    v = DefaultMaintainerVerifier()
    assert v.verify("octo/widget", "carol") is True
    assert v.verify("octo/widget", "alice") is False


def test_default_verifier_bad_env_is_empty(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_MAINTAINERS", "not json")
    v = DefaultMaintainerVerifier()
    assert v.verify("octo/widget", "carol") is False  # fail-closed on bad config


def test_test_verifier_seeded_pairs():
    v = TestMaintainerVerifier([("octo/widget", "alice")])
    assert v.verify("octo/widget", "alice") is True
    assert v.verify("octo/widget", "bob") is False
    v.seed("octo/widget", "bob")
    assert v.verify("octo/widget", "bob") is True
