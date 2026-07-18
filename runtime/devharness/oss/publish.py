"""OSS PR publish (Track 2, §S5) — push the fork-branch + open the upstream PR.

The B4.5 flow commits the contribution to a local branch (``devharness-oss/<task>``) and stops. This lands
it as a real pull request: push the branch to the GitHub push-remote with a token, then open the PR via the
GitHub REST API. Emits ``oss_pr_opened``. The token is read from the environment (GH_TOKEN/GITHUB_TOKEN) and
NEVER logged — the authenticated push URL is built per call, not persisted, and scrubbed from any error.

Fails loudly (``PublishError``) on a push or PR-open failure — a publish must never silently no-op.
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import msgspec

from devharness.events.registry import OssPrOpened

_API = "https://api.github.com"


class PublishError(RuntimeError):
    """A push or PR-open failed. The publish fails closed rather than reporting a contribution that isn't up."""


def resolve_token(explicit: str | None = None) -> str:
    tok = explicit or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not tok:
        raise PublishError("no GitHub token: set GH_TOKEN (or GITHUB_TOKEN) to push + open the PR")
    return tok


# The token is supplied to git through the ENV (GIT_PUSH_TOKEN), referenced by NAME from an inline
# credential helper — so it never lands in the process argv (where `ps` / /proc/<pid>/cmdline would expose
# it to any local user). The push URL is the bare repo URL with no secret in it.
_CRED_HELPER = '!f() { echo username=x-access-token; echo "password=$GIT_PUSH_TOKEN"; }; f'


def _push_branch(worktree_path: str, fork_branch: str, push_repo: str, token: str, timeout: int = 120) -> None:
    url = f"https://github.com/{push_repo}.git"
    env = {**os.environ, "GIT_PUSH_TOKEN": token, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(
        ["git", "-C", worktree_path, "-c", f"credential.helper={_CRED_HELPER}",
         "push", url, f"{fork_branch}:{fork_branch}"],
        capture_output=True, text=True, env=env, timeout=timeout,
    )
    if proc.returncode != 0:
        raise PublishError(f"git push failed (rc={proc.returncode}): {proc.stderr.strip().replace(token, '***')}")


def _open_pr(pr_repo: str, head: str, base: str, title: str, body: str, token: str) -> dict:
    payload = json.dumps({"title": title, "head": head, "base": base, "body": body}).encode()
    req = urllib.request.Request(
        f"{_API}/repos/{pr_repo}/pulls", data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "devharness-oss"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise PublishError(f"open PR failed (HTTP {e.code}): {e.read().decode()[:500]}") from e
    except urllib.error.URLError as e:
        raise PublishError(f"open PR failed (network): {e}") from e


def publish_pull_request(*, worktree_path, fork_branch, push_repo, pr_repo, base_branch, fork_owner,
                         title, body, oss_task_id, upstream_repo, event_bus, correlation_id,
                         now_millis=None, token=None) -> dict:
    """Push ``fork_branch`` to ``push_repo``, open a PR (head ``fork_branch`` -> base ``base_branch``) on
    ``pr_repo``, and emit ``oss_pr_opened``. ``head`` is ``<fork_owner>:<branch>`` for a cross-repo fork PR,
    or just ``<branch>`` when the fork and the PR repo share an owner (same-repo PR). Returns
    {pr_url, pr_number, fork_branch}."""
    tok = resolve_token(token)
    _push_branch(worktree_path, fork_branch, push_repo, tok)
    head = fork_branch if fork_owner == pr_repo.split("/")[0] else f"{fork_owner}:{fork_branch}"
    resp = _open_pr(pr_repo, head, base_branch, title, body, tok)
    at = (now_millis or (lambda: int(time.time() * 1000)))()
    event_bus.emit_sync(
        "oss_pr_opened",
        msgspec.to_builtins(OssPrOpened(
            oss_task_id=oss_task_id, upstream_repo=upstream_repo, fork_branch=fork_branch,
            base_branch=base_branch, pr_repo=pr_repo, pr_number=resp["number"], pr_url=resp["html_url"],
            opened_at_millis=at, correlation_id=correlation_id,
        )),
        correlation_id=correlation_id,
    )
    return {"pr_url": resp["html_url"], "pr_number": resp["number"], "fork_branch": fork_branch}
