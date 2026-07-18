"""Tests for the changelog_sha_resolvable check.

Most tests inject a fake git runner so they exercise the check deterministically
without a real repository; one integration test uses a real git repo (skipped
if git is unavailable).
"""

import shutil
import subprocess

import pytest

from specledger.checks import (
    CHANGELOG_SHA_RESOLVABLE,
    _changelog_shas,
    check_changelog_sha_resolvable,
)


def details(violations):
    return [v.detail for v in violations]


def git_head_sha(root):
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_fake_git(*, is_repo=True, resolvable_shas=()):
    resolvable = set(resolvable_shas)

    def fake_git(repo_root, args):
        if args[:2] == ["rev-parse", "--is-inside-work-tree"]:
            return subprocess.CompletedProcess(
                args, 0 if is_repo else 128, stdout="true\n" if is_repo else "", stderr=""
            )
        if args[:1] == ["rev-parse"]:
            # last arg is "<sha>^{commit}"
            target = args[-1]
            sha = target.split("^")[0]
            ok = sha in resolvable
            return subprocess.CompletedProcess(args, 0 if ok else 128, stdout="", stderr="")
        raise AssertionError(f"unexpected git args: {args}")

    return fake_git


def test_all_shas_resolvable_passes(tmp_path, repo_builder):
    changelog = "closed at `a0537c9` and `4cab232`\n"
    root = repo_builder(tmp_path, changelog=changelog)
    fake = make_fake_git(is_repo=True, resolvable_shas=["a0537c9", "4cab232"])
    assert check_changelog_sha_resolvable(root, git_runner=fake) == []


def test_unresolvable_sha_flagged(tmp_path, repo_builder):
    changelog = "closed at `a0537c9` and `deadbee`\n"
    root = repo_builder(tmp_path, changelog=changelog)
    fake = make_fake_git(is_repo=True, resolvable_shas=["a0537c9"])
    violations = check_changelog_sha_resolvable(root, git_runner=fake)
    assert any("'deadbee'" in d for d in details(violations))
    assert all(v.check == CHANGELOG_SHA_RESOLVABLE for v in violations)
    assert all(v.severity == "error" for v in violations)


def test_not_a_git_repo_single_error(tmp_path, repo_builder):
    changelog = "closed at `a0537c9`\n"
    root = repo_builder(tmp_path, changelog=changelog)
    fake = make_fake_git(is_repo=False)
    violations = check_changelog_sha_resolvable(root, git_runner=fake)
    assert len(violations) == 1
    assert "not a git repository" in violations[0].detail


def test_no_shas_passes(tmp_path, repo_builder):
    root = repo_builder(tmp_path, changelog="# Changelog\n\nnothing here, migration `0023`.\n")
    fake = make_fake_git(is_repo=True)
    assert check_changelog_sha_resolvable(root, git_runner=fake) == []


def test_missing_changelog(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    (root / "CHANGELOG.md").unlink()
    violations = check_changelog_sha_resolvable(root, git_runner=make_fake_git())
    assert any("changelog not found" in d for d in details(violations))


def test_migration_numbers_not_treated_as_shas():
    text = "see migration `0023` and `0001`; closed at `a0537c9`.\n"
    assert _changelog_shas(text) == ["a0537c9"]


def test_shas_deduped_preserving_order():
    text = "`a0537c9` then `4cab232` then `a0537c9` again.\n"
    assert _changelog_shas(text) == ["a0537c9", "4cab232"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_integration_real_git_resolves_head(tmp_path, repo_builder):
    root = repo_builder(tmp_path, changelog="placeholder\n", git_init=True)
    head = git_head_sha(root)
    # Rewrite changelog to reference the real HEAD sha, then re-check with real git.
    (root / "CHANGELOG.md").write_text(f"closed at `{head[:9]}`\n", encoding="utf-8")
    assert check_changelog_sha_resolvable(root) == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_integration_real_git_flags_bogus(tmp_path, repo_builder):
    root = repo_builder(tmp_path, changelog="closed at `0000000`\n", git_init=True)
    violations = check_changelog_sha_resolvable(root)
    assert any("0000000" in d for d in details(violations))
