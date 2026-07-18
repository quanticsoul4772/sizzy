"""Developer role — the single writer (B2.3, §Architecture R3).

The only role with write tools. An Agent SDK worker (OQ2, spec rev 0.3.7): a
runtime-driven subprocess with setting_sources=[], MCP-scoped tools (parallax +
mcp-reasoning + the in-runtime devharness-aci ACI server), cwd = its isolated
worktree. Holds the single write lock for the task; the ACI's structured write
actions are gate-checked. Terminal-outcome wiring lands in B2.6; B2.3 acquires the
lock, starts the task in an isolated worktree, runs the worker, and releases.
"""

import json
import subprocess
import time
from fnmatch import fnmatch

import claude_agent_sdk as sdk
import msgspec

from devharness.aci.editor import EditorActions
from devharness.aci.server import ACI_SERVER_NAME, aci_tool_names, make_aci_mcp_server
from devharness.aci.shell import ShellActions
from devharness.aci.test_runner import TestRunnerActions
from devharness.checkpoint.base import take_checkpoint
from devharness.checkpoint.rewind import rewind_to
from devharness.events.registry import OssWorktreeCreated, TaskStarted, WriteApplied
from devharness.gates import antibody_screen as _antibody_screen  # noqa: F401  (register the M7 screen)
from devharness.gates import scope_guard as _scope_guard  # noqa: F401  (register secret/scope gates)
from devharness.gates import secret_guard as _secret_guard  # noqa: F401
from devharness.gates import workflow_guard as _workflow_guard  # noqa: F401  (register workflow_guard for F2 realized-diff check)
from devharness.gates.base import GateDeny, evaluate
from devharness.gates.registry import GATES
from devharness.oss.commit_identity import commit_with_identity, get_commit_identity
from devharness.verifier.base import VerifierOk
from devharness.verifier.builtin._common import looks_like_prompt_injection
from devharness.lock.base import SingleWriterLock
from devharness.mcp.mcp_reasoning import MCP_REASONING_TOOLS
from devharness.mcp.parallax import PARALLAX_TOOLS
from devharness.models import default_model
from devharness.worktree.hygiene import purge_bytecode_caches
from devharness.roles.base import AgentRole, progress_from_messages
from devharness.worktree.isolate import create_worktree

SERVER_TOOL_CATALOG = {"parallax": PARALLAX_TOOLS, "mcp-reasoning": MCP_REASONING_TOOLS}

# Defense-in-depth (rev 0.3.22): the developer's writes must go through the ACI — the
# scope-gated editor or the realized-diff-enforced shell. Hard-block the built-in write/exec
# tools so the worker cannot reach a write path the harness does not see, even under
# bypassPermissions. Built-in read tools stay available (read-only, no containment risk).
_BUILTIN_WRITE_EXEC_TOOLS = ["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"]


class DeveloperRole(AgentRole):
    ALLOWED_MCP_SERVERS = ["parallax", "mcp-reasoning", "devharness-aci"]

    def __init__(self, *, event_bus, conn, context, base_path=".", base_ref=None, scratch_branch=None,
                 lock=None, query_fn=None,
                 worktree_factory=None, checkpoint_fn=None, write_hook=None, oss_verify_fn=None,
                 mcp_server_configs=None, sandbox_launcher=None, worker_test_command=None,
                 scope_widener=None, now_millis=None, model=None):
        self.event_bus = event_bus
        self.conn = conn
        self.context = context  # harness-assembled
        self.base_path = base_path
        self.base_ref = base_ref  # B3.1: when set, the worktree starts from this branch/commit (existing repo)
        # external-target write: when set, the non-OSS worktree is created on this named scratch branch (off
        # base_ref/HEAD) so a feature built into an external repo lands on its own branch, never that repo's
        # main. None (the default) keeps the detached, discard-after-run behavior used for devharness-internal
        # builds — so every existing path/test is unchanged. The post-certification commit is the driver's job.
        self.scratch_branch = scratch_branch
        self.lock = lock or SingleWriterLock()
        self._query_fn = query_fn or sdk.query
        self._worktree_factory = worktree_factory or create_worktree
        self._checkpoint_fn = checkpoint_fn or take_checkpoint
        # write_hook(editor, shell, test_runner): synthetic worker tool calls under the lock
        # (used by acceptance tests where the SDK worker is mocked). Default: no-op.
        self._write_hook = write_hook
        # Advisory MCP server launch specs (parallax / mcp-reasoning) injected by the runtime.
        # The ACI server is always bound (the in-process write surface); these are added only
        # when a real config is supplied — an empty {} placeholder is rejected by the SDK.
        self._mcp_server_configs = dict(mcp_server_configs or {})
        # #1a (rev 0.3.24): when set, the ACI shell + test-runner run through this §S5 SandboxLauncher
        # for out-of-worktree host containment (opt-in; default None = host execution).
        self._sandbox_launcher = sandbox_launcher
        # The command the worker's ACI test_runner self-tests with — aligned to the verifier's command so the
        # worker iterates against the SAME tests (e.g. cargo test for a Rust target). None → the test_runner's
        # pytest default (internal Python builds unchanged).
        self._worker_test_command = worker_test_command
        # Dispatch-time scope widener: async (worktree_path, planned_task) -> [extra repo-relative files the
        # change must ALSO touch]. WIDEN-ONLY — the result is UNIONed onto scope_boundary, never subtracted,
        # so it can never box the worker (worst case []). None → scope is the model's decompose globs, unchanged.
        self._scope_widener = scope_widener
        self._effective_scope = None  # the per-run union (model scope ∪ widener); governs both enforcement layers
        # B4.5-fix: oss_verify_fn(planned_task, developer, conn, event_bus) -> VerifierResult runs the
        # OSS task's verifier inside the lock, before the bot-identity commit (commit-after-verifier).
        self._oss_verify_fn = oss_verify_fn
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))
        self.model = model or default_model()  # explicit kwarg > DEVHARNESS_MODEL > built-in default
        self.worktree = None  # set during run() so callers can inspect the active worktree
        self.progress = 0
        self.total_cost_usd = 0.0
        self.checkpoint = None  # the baseline checkpoint taken at task start
        self.oss_verify_result = None  # B4.5-fix: the OSS in-lock verifier result (None for non-OSS)
        self.scope_violation = None  # rev 0.3.21: out-of-scope realized-diff paths, if any (else None)
        self.gate_denial = None  # rev 0.3.25: (gate_name, reason) when an OSS content gate denies the realized diff

    @property
    def allowed_mcp_servers(self) -> list[str]:
        return list(self.ALLOWED_MCP_SERVERS)

    @property
    def tool_inventory(self) -> list[str]:
        # the developer is the writer: include the ACI write actions, no mutation filter
        tools = []
        for server in ("parallax", "mcp-reasoning"):
            for tool in SERVER_TOOL_CATALOG[server]:
                tools.append(f"mcp__{server}__{tool}")
        tools += aci_tool_names()
        return tools

    @classmethod
    def assemble_context(cls, conn, correlation_id) -> dict:
        events = conn.execute(
            "SELECT event_type FROM events WHERE correlation_id = ? ORDER BY seq", (correlation_id,)
        ).fetchall()
        artifacts = conn.execute(
            "SELECT artifact_id FROM artifacts WHERE correlation_id = ?", (correlation_id,)
        ).fetchall()
        return {
            "correlation_id": correlation_id,
            "prior_events": [row[0] for row in events],
            "prior_artifacts": [row[0] for row in artifacts],
        }

    @classmethod
    def spawn(cls, *, conn, correlation_id, event_bus, **kwargs):
        return cls(event_bus=event_bus, conn=conn, context=cls.assemble_context(conn, correlation_id), **kwargs)

    async def run(self, planned_task, correlation_id):
        token = self.lock.acquire("developer", correlation_id, self.event_bus, self.conn)
        worktree = None
        try:
            if getattr(planned_task, "is_oss", False) and planned_task.oss_envelope is not None:
                # B4.4: a fork-branch worktree (devharness-oss/<task_id>) off the upstream target branch
                env = planned_task.oss_envelope
                worktree = self._worktree_factory(
                    planned_task.task_id, self.base_path,
                    oss_task_id=planned_task.task_id, oss_target_branch=env.target_branch,
                )
                self._emit(
                    "oss_worktree_created",
                    OssWorktreeCreated(
                        oss_task_id=planned_task.task_id, upstream_repo=env.upstream_repo,
                        target_branch=env.target_branch, fork_branch=worktree.fork_branch,
                        worktree_path=worktree.path, created_at_millis=self._now_millis(),
                        correlation_id=correlation_id,
                    ),
                    correlation_id,
                )
            elif self.scratch_branch is not None:  # external-target write: land on a named scratch branch
                worktree = self._worktree_factory(planned_task.task_id, self.base_path, self.base_ref,
                                                  scratch_branch=self.scratch_branch)
            elif self.base_ref is not None:  # B3.1 existing-repo worktree off a base ref
                worktree = self._worktree_factory(planned_task.task_id, self.base_path, self.base_ref)
            else:
                worktree = self._worktree_factory(planned_task.task_id, self.base_path)
            self.worktree = worktree
            self._emit(
                "task_started",
                TaskStarted(
                    task_id=planned_task.task_id, role="developer", worktree_path=worktree.path,
                    correlation_id=correlation_id, started_at_millis=self._now_millis(),
                ),
                correlation_id,
            )
            # baseline checkpoint so any later rewind has a known-good state (B2.4)
            self.checkpoint = self._checkpoint_fn(
                planned_task.task_id, worktree.path, correlation_id, self.event_bus, self.conn
            )
            # F4 (rev 0.3.67): for an OSS task, the description/claim are UNTRUSTED external text that
            # go RAW into the worker prompt (there is no context-separation seam for an instruction the
            # worker must act on). Marker-scan them and fail SAFE before the SDK worker ever sees them —
            # reuses the gate_denial plumbing (the director turns it into a rejected terminal, no commit).
            refusal = self._oss_injection_refusal(planned_task)
            if refusal:
                self.gate_denial = ("injection_guard", refusal)
                return worktree
            await self._run_worker(planned_task, worktree, correlation_id)
            # Bytecode-cache hygiene (rev 0.3.58): the worker exercising the code generates
            # __pycache__/.pytest_cache — compiler exhaust, not writes. Purge BEFORE the scope check
            # (which reads git status independently of _realized_diff), or a gitignore-less target
            # rejects a legitimate task over cache files (a live refactor was rejected exactly so).
            purge_bytecode_caches(worktree.path)
            # Realized-diff scope enforcement (rev 0.3.21): bind the scope boundary to the actual
            # worktree changes, not just editor tool-calls — a worker can write via the ACI shell or
            # built-ins. Out-of-scope change -> rewind clean + flag (the director emits the rejected
            # terminal and skips verify/review); in-scope non-editor writes are tracked.
            self._enforce_worktree_scope(planned_task, worktree, correlation_id)
            if self.scope_violation:
                return worktree
            # Realized-diff content gates (rev 0.3.25, #C1/#C2): the §S5 OSS secret_guard /
            # scope_guard read context["diff_content"], which only exists AFTER the worker runs —
            # at admission there is no diff, so they passed vacuously. Run them here, in-lock, on
            # the actual worktree diff. A deny rewinds clean + flags; the director rejects.
            self._enforce_content_gates(planned_task, worktree, correlation_id)
            if self.gate_denial:
                return worktree
            # B4.5 ordering fix: for an OSS task the verifier runs INSIDE the lock against the
            # UNCOMMITTED worktree (so working-tree-stash verifiers — bugfix/refactor — reach their
            # baseline correctly), and the OSS bot-identity commit lands ONLY if the verifier passes.
            # The fork-branch therefore never carries unverified commits (verifier-first, C2). On
            # failure run_verifier (inside oss_verify_fn) rewinds + emits the terminal — no commit.
            if getattr(planned_task, "is_oss", False) and planned_task.oss_envelope is not None:
                self.oss_verify_result = None
                if self._oss_verify_fn is not None:
                    result = await self._oss_verify_fn(planned_task, self, self.conn, self.event_bus)
                    self.oss_verify_result = result
                    if isinstance(result, VerifierOk):
                        env = planned_task.oss_envelope
                        identity = get_commit_identity(env.upstream_repo, getattr(planned_task, "task_class", ""))
                        commit_with_identity(
                            worktree.path, f"devharness OSS contribution {planned_task.task_id}", identity,
                            oss_task_id=planned_task.task_id, upstream_repo=env.upstream_repo,
                            event_bus=self.event_bus, correlation_id=correlation_id, now_millis=self._now_millis,
                        )
        finally:
            self.lock.release(token, self.event_bus, self.conn)
            # §S9 per-role spend (rev 0.3.56): the worker session's realized cost, emitted even on the
            # early-return denial paths (this finally). Zero-cost runs (mocked query_fn) emit nothing.
            if self.total_cost_usd > 0:
                self.event_bus.emit_sync(
                    "cost_spent",
                    {"role": "developer", "amount_usd": self.total_cost_usd, "model": self.model,
                     "task_id": planned_task.task_id, "spent_at_millis": self._now_millis(),
                     "correlation_id": correlation_id},
                    correlation_id=correlation_id,
                )
        return worktree

    def build_aci(self, worktree, scope_boundary, correlation_id, task_id, task_class=""):
        editor = EditorActions(
            worktree=worktree, scope_boundary=scope_boundary, event_bus=self.event_bus,
            conn=self.conn, correlation_id=correlation_id, task_id=task_id, task_class=task_class,
        )
        return (
            editor,
            ShellActions(worktree=worktree, sandbox_launcher=self._sandbox_launcher),
            TestRunnerActions(worktree=worktree, sandbox_launcher=self._sandbox_launcher,
                              default_command=self._worker_test_command),
        )

    async def _run_worker(self, planned_task, worktree, correlation_id):
        # Widen scope against the WORKTREE (where a dependency's files already exist, unlike HEAD at plan time):
        # union the model's globs with the files the change must also touch. Both enforcement layers (the ACI
        # editor below + _enforce_worktree_scope) then honour the union.
        effective_scope = list(planned_task.scope_boundary)
        if self._scope_widener is not None:
            for p in (await self._scope_widener(worktree.path, planned_task)) or []:
                if p not in effective_scope:
                    effective_scope.append(p)
        self._effective_scope = effective_scope
        editor, shell, test_runner = self.build_aci(
            worktree, effective_scope, correlation_id, planned_task.task_id,
            getattr(planned_task, "task_class", ""),
        )
        if self._write_hook is not None:
            self._write_hook(editor, shell, test_runner)  # synthetic worker writes under the lock
        # The ACI server is the in-process write surface (always bound). parallax/mcp-reasoning
        # are advisory and bound only when the runtime injects a real launch spec.
        mcp_servers = {ACI_SERVER_NAME: make_aci_mcp_server(editor, shell, test_runner)}  # live SDK MCP binding (B2.7)
        for name in ("parallax", "mcp-reasoning"):
            cfg = self._mcp_server_configs.get(name)
            if cfg:
                mcp_servers[name] = cfg
        options = sdk.ClaudeAgentOptions(
            setting_sources=[], mcp_servers=mcp_servers, cwd=worktree.path, model=self.model,
            # The developer's tool surface is exactly its MCP inventory (the scope-gated ACI
            # editor/shell/test_runner + advisory parallax/mcp-reasoning) — no built-in Edit/Write/
            # Bash, so the ONLY write path is the ACI editor. bypassPermissions lets the autonomous
            # worker use those tools without an interactive prompt; containment is the ACI gate +
            # worktree + scope allowlist, not the SDK permission layer.
            allowed_tools=self.tool_inventory, disallowed_tools=_BUILTIN_WRITE_EXEC_TOOLS,
            permission_mode="bypassPermissions",
        )
        prompt = self._worker_prompt(planned_task, correlation_id)
        from devharness.sdk_query import run_query  # overage auth-fallback (rev 0.4.0)
        async for message in run_query(self._query_fn, prompt, options):
            self.progress += progress_from_messages([message])
            cost = getattr(message, "total_cost_usd", None)
            if cost is not None:
                self.total_cost_usd += float(cost)

    def _worktree_changed_paths(self, worktree) -> list[str]:
        """Repo-relative paths changed in the worktree. Renames yield the destination. NOTE:
        gitignore only excludes build artifacts when the target repo HAS one — the rev-0.3.58
        cache purge in run() (before the scope check) is what actually keeps __pycache__/*.pyc
        out of this listing for gitignore-less targets."""
        proc = subprocess.run(
            ["git", "-C", worktree.path, "status", "--porcelain", "-uall"],
            capture_output=True, text=True,
        )
        paths = []
        for line in proc.stdout.splitlines():
            entry = line[3:].strip() if len(line) > 3 else line.strip()
            if " -> " in entry:  # rename: the destination path is what was written
                entry = entry.split(" -> ", 1)[1]
            entry = entry.strip().strip('"')
            if entry:
                paths.append(entry)
        return paths

    def _enforce_worktree_scope(self, planned_task, worktree, correlation_id) -> None:
        """Enforce scope_boundary on the realized worktree diff (rev 0.3.21). Sets
        self.scope_violation + rewinds clean on any out-of-scope path; otherwise tracks
        in-scope realized writes the editor did not already emit."""
        changed = self._worktree_changed_paths(worktree)
        boundary = list(self._effective_scope or planned_task.scope_boundary)  # the dispatch-time union
        out_of_scope = [p for p in changed if not any(fnmatch(p, glob) for glob in boundary)]
        if out_of_scope:
            self.scope_violation = out_of_scope
            rewind_to(self.checkpoint, self.event_bus, self.conn, clean=True)
            return
        already_tracked = set()
        for (payload,) in self.conn.execute("SELECT payload FROM events WHERE event_type = 'write_applied'"):
            record = json.loads(payload)
            if record.get("task_id") == planned_task.task_id:
                already_tracked.add(record.get("target_path"))
        for path in changed:
            if path in already_tracked:
                continue
            self._emit(
                "write_applied",
                WriteApplied(
                    task_id=planned_task.task_id, worktree_path=worktree.path, target_path=path,
                    action_kind="worktree_diff", correlation_id=correlation_id,
                    applied_at_millis=self._now_millis(), observed_success=True,
                    task_class=getattr(planned_task, "task_class", "") or "",
                ),
                correlation_id,
            )

    def _realized_diff(self, worktree) -> str:
        """The unified diff of all worktree changes vs the baseline checkpoint. Purges bytecode caches
        first (rev 0.3.58) — gitignore only excludes them when the target HAS one, and the verifier's
        own pytest run regenerates caches after the in-run purge. Stages everything to capture new
        files as added lines, diffs against HEAD (the checkpoint commit), then unstages — leaving the
        working tree untouched."""
        base = worktree.path
        purge_bytecode_caches(base)
        subprocess.run(["git", "-C", base, "add", "-A"], capture_output=True, text=True)
        diff = subprocess.run(["git", "-C", base, "diff", "--cached", "HEAD"], capture_output=True, text=True).stdout
        subprocess.run(["git", "-C", base, "reset", "-q"], capture_output=True, text=True)
        return diff

    def _enforce_content_gates(self, planned_task, worktree, correlation_id) -> None:
        """Run the §S5 OSS content gates (secret_guard, scope_guard) on the REALIZED diff (#C1/#C2).
        These read diff_content, which is empty at admission, so they only enforce here. OSS-only:
        the cumulative-LOC limit + the entropy axis would false-positive on legitimate local work."""
        if not getattr(planned_task, "is_oss", False):
            return
        diff = self._realized_diff(worktree)
        # Fail-closed (audit F3): an empty/uncomputable realized diff must NOT admit — the content gates
        # would pass vacuously on an untrusted contribution we cannot inspect. An OSS task always produces
        # an inspectable change; an empty diff means git failed or nothing was written → refuse.
        if not diff.strip():
            self.gate_denial = ("content_gates", "empty or uncomputable realized diff — the OSS contribution cannot be inspected")
            rewind_to(self.checkpoint, self.event_bus, self.conn, clean=True)
            return
        ctx = {
            "touched_paths": self._worktree_changed_paths(worktree),  # the REALIZED changed paths
            "diff_content": diff,
            "task_id": planned_task.task_id,
            "correlation_id": correlation_id,
            "conn": self.conn,  # #M7: antibody_screen reads the active library from the projection
        }
        # workflow_guard (audit F2) is checked HERE on the realized changed paths — at admission it only
        # saw declared scope globs (never the diff), so a `.github/**`-scoped task could write a real
        # workflow file unchecked. #M7: antibody_screen applies the retro-learned operator-approved patterns.
        for name in ("workflow_guard", "secret_guard", "scope_guard", "antibody_screen"):
            gate = GATES.get(name)
            if gate is None:
                continue
            result = evaluate(gate, ctx, self.event_bus)  # runs the gate AND emits gate_fired
            if isinstance(result, GateDeny):
                self.gate_denial = (name, result.reason)
                rewind_to(self.checkpoint, self.event_bus, self.conn, clean=True)
                return

    def _signed_spec_context(self, correlation_id):
        """The signed spec's problem statement + operator-confirmed assumptions for this correlation."""
        row = self.conn.execute(
            "SELECT payload_json FROM artifacts WHERE artifact_type = 'spec' AND correlation_id = ? "
            "AND signed = 1 ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
            (correlation_id,),
        ).fetchone()
        if not row:
            return "", []
        spec = json.loads(row[0])
        return spec.get("problem", ""), [a.get("text", "") for a in spec.get("assumptions", [])]

    def _prior_rejection(self, task_id) -> str:
        """The independent verifier's refutation from the most-recent REJECTED verifier_outcome for this task,
        fed back so a re-dispatched worker self-corrects. The useful text lives in
        evidence.parallax_verify.output (a STRING; json-parse for `findings`, else use it raw); the event
        `detail` is generic. Empty when there is no prior rejection (first attempt — back-compat)."""
        latest = None
        for (payload,) in self.conn.execute("SELECT payload FROM events WHERE event_type = 'verifier_outcome'"):
            rec = json.loads(payload)
            if rec.get("task_id") == task_id and rec.get("passed") is False:
                latest = rec
        if latest is None:
            return ""
        out = ((latest.get("evidence") or {}).get("parallax_verify") or {}).get("output")
        if not out:
            return (latest.get("detail") or "").strip()
        try:
            obj = json.loads(out)
            findings = obj.get("findings") if isinstance(obj, dict) else None
            if findings:
                return "\n".join(f"- {f}" for f in findings)
        except (ValueError, TypeError):
            pass
        return str(out).strip()

    def _oss_injection_refusal(self, planned_task) -> str | None:
        """F4: for an OSS task, return a refusal reason if the untrusted description or spec_claim carries
        prompt-injection directive structure (conservative full-phrase markers — a legit task does not trip
        them); else None. Non-OSS tasks carry director-authored (trusted) descriptions and are not scanned."""
        if not getattr(planned_task, "is_oss", False):
            return None
        for span in (planned_task.description, getattr(planned_task, "spec_claim", "") or ""):
            if looks_like_prompt_injection(span):
                return "untrusted OSS task text carries prompt-injection directive structure"
        return None

    def _worker_prompt(self, planned_task, correlation_id) -> str:
        """The worker's instruction: what to build (task description + signed-spec intent), the exact claim it
        is verified against, the binding stated location, and — on a re-dispatch — why the prior attempt was
        rejected, so it self-corrects."""
        problem, assumptions = self._signed_spec_context(correlation_id)
        # rev 0.3.71: render the EFFECTIVE scope (model globs ∪ dispatch-time widener), not the bare
        # plan globs — the widener's union governed both enforcement layers but the prompt still
        # told the worker the narrow scope, so it obeyed and never touched the widened files (the
        # widener only stopped enforcement from rejecting edits the worker was told not to make).
        boundary = list(self._effective_scope or planned_task.scope_boundary)
        widened = [p for p in boundary if p not in planned_task.scope_boundary]
        parts = [
            f"You are the developer worker for task {planned_task.task_id} (class: {planned_task.task_class}).",
            f"Scope boundary — you may ONLY create or edit files matching these globs: {boundary}.",
        ]
        if widened:
            parts.append(
                "Scope analysis found these files must ALSO be updated for the change to work "
                f"(already included in your scope above): {widened}. Update them even if the task "
                "description reads narrower — an existing test contradicting the change is part of "
                "the change."
            )
        parts += [
            "",
            f"Task to implement:\n{planned_task.description}",
        ]
        claim = getattr(planned_task, "spec_claim", "") or ""
        if claim and claim != planned_task.description:
            parts += ["", f"You are independently verified against this exact claim — your change must satisfy it:\n{claim}"]
        if problem:
            parts += ["", f"Signed-spec problem this serves:\n{problem}"]
        if assumptions:
            parts += ["", "Operator-confirmed design intent:"] + [f"  - {a}" for a in assumptions if a]
        prior = self._prior_rejection(planned_task.task_id)
        if prior:
            parts += [
                "",
                "A PRIOR attempt at this task was REJECTED by the independent verifier, which found:",
                prior,
                "Address this specifically: change the diff to satisfy the claim — in particular make the "
                "change at the location / via the approach the task states, not a different one.",
            ]
        parts += [
            "",
            "Implement this end to end with the devharness-aci editor/shell/test_runner tools: write the "
            "code and its unit tests, run the tests, and iterate until they pass. Implement at the location / "
            "via the approach the task description states — the scope globs are an OUTER bound, not a license "
            "to choose a different file or location. Do not write outside the scope boundary.",
            "On every write_file / append_to_file call, set predicted_success to your honest probability "
            "(0.0-1.0) that THAT write is in-scope and correct on the first try — be calibrated (it feeds "
            "the SC-5 trust signal); do not always send a high or default value.",
        ]
        return "\n".join(parts)

    def _emit(self, event_type, struct, correlation_id) -> None:
        self.event_bus.emit_sync(event_type, msgspec.to_builtins(struct), correlation_id=correlation_id)
