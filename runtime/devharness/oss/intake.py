"""Hardened OSS intake (B4.1, §S5).

The entry point for an external OSS request: before the request can be recorded (and thus before
the director will plan an `is_oss=True` task for it), three checks run fail-closed in order —
license allowlist, maintainer verification, context-injection scan. A failing check emits an
`intake_decision(rejected, reason)` and records NO intake, so the director's B4.0 intake-required
check refuses the task. An all-clean request emits BOTH `oss_task_intake` AND
`intake_decision(accepted)`.
"""

import json
import time
import urllib.error
import urllib.request

from devharness.oss.cooldowns import CooldownConfig, check_cooldown, check_intake_rate, emit_cooldown_refusal
from devharness.oss.injection_scan import scan_repo_files, scan_texts
from devharness.oss.license_allowlist import is_license_allowed
from devharness.oss.maintainer import DefaultMaintainerVerifier


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def _decision(event_bus, intake_correlation_id, decision, rejection_reason, detected_patterns, correlation_id, at):
    event_bus.emit_sync(
        "intake_decision",
        {"intake_correlation_id": intake_correlation_id, "decision": decision,
         "rejection_reason": rejection_reason, "detected_patterns": detected_patterns,
         "decision_at_millis": at, "correlation_id": correlation_id},
        correlation_id=correlation_id,
    )


def _owner_repo(repo_url):
    """Extract "owner/repo" from a GitHub repo URL or a bare "owner/repo" string; None if unparseable."""
    s = (repo_url or "").strip()
    if s.endswith(".git"):
        s = s[:-4]
    if s.startswith("http://") or s.startswith("https://"):
        s = s.split("github.com/", 1)[1] if "github.com/" in s else ""
    elif s.startswith("git@"):
        s = s.split(":", 1)[1] if ":" in s else ""
    parts = [p for p in s.split("/") if p]
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None


def fetch_upstream_license(repo_url, *, token=None, timeout=10.0):
    """Fetch the upstream repo's ACTUAL SPDX license via the GitHub REST API
    (GET /repos/{owner}/{repo}/license) and return its `license.spdx_id`. Returns None for an
    unlicensed repo (404) or an unparseable repo url. The id may be "NOASSERTION" when GitHub cannot
    map the LICENSE to a recognized SPDX id — the caller MUST treat both None and "NOASSERTION" as a
    verification failure, never a match (F7, claudedocs/oss-trust-model-prerequisites.md)."""
    owner_repo = _owner_repo(repo_url)
    if owner_repo is None:
        return None
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "devharness-oss-intake"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com/repos/{owner_repo}/license", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:  # no LICENSE detected — unlicensed repo
            return None
        raise
    return (data.get("license") or {}).get("spdx_id")


def process_intake(envelope, description, event_bus, *, intake_correlation_id, correlation_id,
                   maintainer_verifier=None, license_fetcher=fetch_upstream_license, extra_texts=(), now_millis=None,
                   conn=None, cooldown_config=None, repo_path=None) -> str:
    """Run the cooldown gate then the three intake-hardening checks fail-closed; record + accept, or reject.

    Returns "accepted" or "rejected". On accept, emits oss_task_intake + intake_decision(accepted).
    On reject, emits only intake_decision(rejected, reason) — no oss_task_intake is recorded.
    When ``conn`` is supplied, an active requester cooldown refuses the intake before the three axes,
    and a successful intake runs the rate check to potentially trip a cooldown for the next attempt.
    """
    verifier = maintainer_verifier or DefaultMaintainerVerifier()
    at = _now(now_millis)

    # 0. requester cooldown (rate-limit / revocation) — refuse before the three axes
    if conn is not None and check_cooldown(envelope.requester_id, conn, lambda: at).active:
        _decision(event_bus, intake_correlation_id, "rejected", "requester_in_cooldown", [], correlation_id, at)
        emit_cooldown_refusal(event_bus, envelope.requester_id, correlation_id, lambda: at)
        return "rejected"

    # 1. license allowlist
    if not is_license_allowed(envelope.license_spdx):
        _decision(event_bus, intake_correlation_id, "rejected", "license_disallowed", [], correlation_id, at)
        return "rejected"

    # 1b. verify the declared license against the upstream repo's REAL license (F7)
    fetched = license_fetcher(envelope.upstream_repo)
    if fetched is None or fetched == "NOASSERTION" or fetched != envelope.license_spdx:
        _decision(event_bus, intake_correlation_id, "rejected",
                  f"license verification failed: upstream SPDX {fetched!r} does not match declared {envelope.license_spdx!r}",
                  [], correlation_id, at)
        return "rejected"

    # 2. maintainer verification
    if not verifier.verify(envelope.upstream_repo, envelope.requester_id):
        _decision(event_bus, intake_correlation_id, "rejected", "maintainer_unverified", [], correlation_id, at)
        return "rejected"

    # 3. context-injection scan over the intake-relevant text AND, when a local upstream clone is
    # supplied, the repo's standard agent-instruction files (README/CONTRIBUTING/AGENTS/CLAUDE — the
    # F4 vectors that reach the developer worker's cwd). Both fail closed on any detected pattern.
    patterns = scan_texts([description, envelope.upstream_repo, envelope.target_branch, *extra_texts])
    patterns += [p for p in scan_repo_files(repo_path) if p not in patterns]
    if patterns:
        _decision(event_bus, intake_correlation_id, "rejected", "injection_detected", patterns, correlation_id, at)
        return "rejected"

    # all clear: record the intake + the accept decision
    event_bus.emit_sync(
        "oss_task_intake",
        {"upstream_repo": envelope.upstream_repo, "license_spdx": envelope.license_spdx,
         "requester_id": envelope.requester_id, "target_branch": envelope.target_branch,
         "intake_at_millis": at, "correlation_id": correlation_id},
        correlation_id=correlation_id,
    )
    _decision(event_bus, intake_correlation_id, "accepted", "", [], correlation_id, at)

    # after a successful intake, run the rate check — it may trip a cooldown for the next attempt
    if conn is not None:
        check_intake_rate(envelope.requester_id, conn, cooldown_config or CooldownConfig(),
                          event_bus, correlation_id, lambda: at)
    return "accepted"
