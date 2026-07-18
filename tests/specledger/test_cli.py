"""Tests for the CLI / orchestration and report shape."""

import json

import pytest

from specledger.checks import run_all_checks
from specledger.cli import main
from specledger.model import Violation
from specledger.report import build_report


def test_build_report_ok_when_empty():
    report = build_report([])
    assert report == {"ok": True, "violations": []}


def test_build_report_shape():
    report = build_report([Violation("c", "error", "d")])
    assert report["ok"] is False
    assert report["violations"] == [{"check": "c", "severity": "error", "detail": "d"}]


def test_run_all_checks_clean_repo(good_repo, monkeypatch):
    # good_repo has a .git marker dir but no real git; the changelog has no SHAs,
    # but is_git_repo on a non-real repo would report not-a-repo -> 1 violation.
    # Use a changelog with no SHAs and a fake-clean git via monkeypatch.
    import specledger.checks as checks

    monkeypatch.setattr(checks, "is_git_repo", lambda root, runner=None: True)
    violations = run_all_checks(good_repo)
    assert violations == []


def test_cli_exit_zero_on_clean(good_repo, monkeypatch, capsys):
    import specledger.checks as checks

    monkeypatch.setattr(checks, "is_git_repo", lambda root, runner=None: True)
    rc = main(["--repo-root", str(good_repo)])
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 0
    assert report["ok"] is True
    assert report["violations"] == []


def test_cli_exit_one_on_violation(tmp_path, repo_builder, monkeypatch, capsys):
    import specledger.checks as checks

    monkeypatch.setattr(checks, "is_git_repo", lambda root, runner=None: True)
    root = repo_builder(tmp_path, migrations=["0001_a", "0003_c"])
    rc = main(["--repo-root", str(root)])
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 1
    assert report["ok"] is False
    assert any(v["check"] == "migration_contiguity" for v in report["violations"])
    assert all(v["severity"] == "error" for v in report["violations"])


def test_cli_repo_not_found(tmp_path, capsys):
    rc = main(["--repo-root", str(tmp_path)])
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 1
    assert report["ok"] is False
    assert report["violations"][0]["check"] == "repo_discovery"


def test_cli_output_is_valid_json(good_repo, monkeypatch, capsys):
    import specledger.checks as checks

    monkeypatch.setattr(checks, "is_git_repo", lambda root, runner=None: True)
    main(["--repo-root", str(good_repo)])
    captured = capsys.readouterr()
    # Should not raise.
    json.loads(captured.out)
