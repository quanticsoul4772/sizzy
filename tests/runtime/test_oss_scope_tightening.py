"""B4.4: OSS scope tightening — reject escapes; intersect an allowlist; B3.1 base preserved."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.oss.scope_oss import is_safe_oss_path, tighten_oss_scope

REPO = "octo/widget"


def test_rejects_escapes():
    assert is_safe_oss_path("src/app.py") is True
    for bad in ("../etc/passwd", "/etc/passwd", "/tmp/x", "../../secret", ".git/config", ".devharness-worktrees/x"):
        assert is_safe_oss_path(bad) is False


def test_tighten_drops_unsafe_keeps_safe():
    globs = ["src/app.py", "src/**", "../escape/**", "/etc/passwd", "tests/**"]
    assert tighten_oss_scope(globs, REPO) == ["src/**", "src/app.py", "tests/**"]


def test_no_allowlist_keeps_b3_base():
    # with no allowlist configured, the B3.1 derivation is preserved (only escapes removed)
    globs = ["src/**", "docs/**", "tests/**"]
    assert tighten_oss_scope(globs, REPO) == ["docs/**", "src/**", "tests/**"]


def test_allowlist_intersection(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_ALLOWED_PATHS", json.dumps({REPO: ["src/**"]}))
    globs = ["src/app.py", "src/util/**", "docs/**", "tests/**"]
    # only paths under the allowlisted src/** survive the intersection
    assert tighten_oss_scope(globs, REPO) == ["src/app.py", "src/util/**"]


def test_allowlist_only_for_named_repo(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_ALLOWED_PATHS", json.dumps({"other/repo": ["src/**"]}))
    # the allowlist targets a different repo -> no intersection here, just escape-filtering
    assert tighten_oss_scope(["src/**", "docs/**"], REPO) == ["docs/**", "src/**"]
