"""Wrong-target contamination guard (rev 0.3.61): warn when a build target carries another store's
scratch branches.

Console builds land per-task scratch branches ``devharness/{task_id}`` in the EXTERNAL target repo,
and task ids embed their correlation (``{correlation_id}-t{n}``, the sole assignment site in
``roles/director.py``; re-drives reuse the same id). Console stores are per-project DBs, so every
correlation that ever built into a repo THROUGH THIS STORE appears in its event log — a scratch
branch whose correlation the store has never seen means the repo was built by a DIFFERENT project's
store. That is exactly a wrong-target incident: a stale re-entered build target landed an entire build
in another project's repo, discovered only at assemble time.

Warning-only, never a block: re-targeting an old repo into a fresh store is legitimate (the operator
confirms and proceeds); dispatch behavior is unchanged. The signal is path-independent by
construction — correlation sets survive a repo/drive migration where any target-path-history
alternative would false-fire on every store.
"""

import re
import subprocess

# a task branch is devharness/{cid}-t{n}; greedy .* recovers a cid that itself ends in -tN
_TASK_BRANCH = re.compile(r"^(.*)-t\d+$")


def foreign_scratch_correlations(conn, target_path) -> list[str]:
    """Correlations of ``devharness/*`` scratch branches in ``target_path`` that this event store
    has never seen, sorted; ``[]`` when none or ``target_path`` is not a git repo.

    Deliberately out of scope: OSS fork branches (``devharness-oss/*`` — a configurable prefix
    landing in ``DEVHARNESS_OSS_UPSTREAM_PATH`` repos, a different entry surface) and a script run's
    ``DEVHARNESS_SCRATCH_BRANCH`` override (lands outside ``devharness/*`` by definition).
    """
    r = subprocess.run(
        ["git", "-C", str(target_path), "branch", "--list", "devharness/*",
         "--format=%(refname:short)"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return []
    cids = set()
    for line in r.stdout.splitlines():
        name = line.strip()
        if not name.startswith("devharness/"):
            continue
        m = _TASK_BRANCH.match(name[len("devharness/"):])
        if m:
            cids.add(m.group(1))
    if not cids:
        return []
    known = {c for (c,) in conn.execute("SELECT DISTINCT correlation_id FROM events")}
    return sorted(cids - known)
