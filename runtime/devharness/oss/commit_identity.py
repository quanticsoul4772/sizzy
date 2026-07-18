"""OSS commit-identity split (B4.5, §S5).

OSS contributions commit under a distinct bot identity, separable from operator commits. The default
identity is intentionally generic and disconnected from any real human; a per-upstream identity can be
configured via DEVHARNESS_OSS_COMMIT_IDENTITIES (a JSON map {upstream_repo: {name, email}}).
``commit_with_identity`` lands a worktree commit with that identity overriding git author + committer
and emits ``commit_identity_assigned``.
"""

import json
import os
import subprocess
import time

import msgspec

from devharness.events.registry import CommitIdentityAssigned
from devharness.worktree.hygiene import purge_bytecode_caches


class CommitIdentity(msgspec.Struct, frozen=True, kw_only=True):
    identity_name: str
    identity_email: str
    assigned_by: str  # "default" | "env_override"


DEFAULT_OSS_COMMIT_IDENTITY = CommitIdentity(
    identity_name="devharness-oss-bot",
    identity_email="oss@devharness.local",
    assigned_by="default",
)


def get_commit_identity(upstream_repo: str, task_class: str) -> CommitIdentity:
    """The OSS commit identity for an upstream: a configured per-repo identity, else the default."""
    raw = os.environ.get("DEVHARNESS_OSS_COMMIT_IDENTITIES", "")
    if raw:
        try:
            entry = json.loads(raw).get(upstream_repo)
        except (json.JSONDecodeError, AttributeError):
            entry = None
        if isinstance(entry, dict) and entry.get("name") and entry.get("email"):
            return CommitIdentity(identity_name=entry["name"], identity_email=entry["email"], assigned_by="env_override")
    return DEFAULT_OSS_COMMIT_IDENTITY


def commit_with_identity(worktree_path, message, identity: CommitIdentity, *, oss_task_id, upstream_repo,
                         event_bus, correlation_id, now_millis=None) -> str:
    """Stage + commit the worktree under ``identity`` (overriding git author AND committer); emit
    commit_identity_assigned with the resulting commit_sha; return the sha. Purges bytecode caches
    first (rev 0.3.58) — the in-lock OSS verifier's test run regenerates them, and a gitignore-less
    upstream would otherwise get caches committed into the PR branch."""
    purge_bytecode_caches(worktree_path)
    subprocess.run(["git", "-C", worktree_path, "add", "-A"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", worktree_path,
         "-c", f"user.name={identity.identity_name}", "-c", f"user.email={identity.identity_email}",
         "commit", "--allow-empty", "-m", message],
        check=True, capture_output=True, text=True,
    )
    sha = subprocess.run(
        ["git", "-C", worktree_path, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    at = (now_millis or (lambda: int(time.time() * 1000)))()
    event_bus.emit_sync(
        "commit_identity_assigned",
        msgspec.to_builtins(CommitIdentityAssigned(
            oss_task_id=oss_task_id, upstream_repo=upstream_repo,
            identity_name=identity.identity_name, identity_email=identity.identity_email,
            assigned_by=identity.assigned_by, commit_sha=sha, assigned_at_millis=at,
            correlation_id=correlation_id,
        )),
        correlation_id=correlation_id,
    )
    return sha
