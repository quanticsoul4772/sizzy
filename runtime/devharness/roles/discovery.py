"""Discovery role — read-only repo analysis that surfaces candidate work items (issue-discovery loop).

The harness could only ever act on an operator-supplied seed; it never found work. This role reads a target
repo's ACTUAL code via a read-only Agent SDK session (Read/Grep/Glob only, no write/exec tools,
setting_sources=[] per commitment 3) plus the explore structural summary, and emits `work_item_candidate`
events into `proj_work_item_queue`. The operator then picks one (a `question_answered` carrying its
candidate_id), which `promote` turns into a spec. Read-only: this role never writes the target repo.

`query_fn` is injectable (default `claude_agent_sdk.query`) so the role is testable without spawning a worker.
"""

import time

import claude_agent_sdk as sdk
import msgspec

from devharness.events.registry import QuestionAsked, WorkItemCandidate
from devharness.explore.runner import run as run_explore_pass
from devharness.models import default_model
from devharness.roles.research import repo_structural_summary
from devharness.roles.synthesis import parse_work_items

# Read-only built-ins: the LLM may read the repo but the write/exec tools are hard-blocked (no containment
# risk for reads). This is the developer's posture inverted — discovery reads, never writes.
_READ_TOOLS = ["Read", "Grep", "Glob"]
_DISALLOWED_WRITE_EXEC = ["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"]


class DiscoveryRole:
    def __init__(self, *, event_bus, conn, target_repo, correlation_id, query_fn=None,
                 mcp_server_configs=None, now_millis=None, model=None, max_candidates=6):
        self.event_bus = event_bus
        self.conn = conn
        self.target_repo = target_repo
        self.correlation_id = correlation_id
        self._query_fn = query_fn or sdk.query
        self._mcp_server_configs = dict(mcp_server_configs or {})
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))
        self.model = model or default_model()  # explicit kwarg > DEVHARNESS_MODEL > built-in default
        self.max_candidates = max_candidates
        self.total_cost_usd = 0.0

    async def run(self) -> list:
        """Analyze the target repo and emit up to max_candidates work_item_candidate events; return their ids."""
        artifact = run_explore_pass(self.target_repo, self.correlation_id)
        summary = repo_structural_summary(artifact)
        text = await self._analyze(summary)
        items = (parse_work_items(text) or [])[: self.max_candidates]
        emitted = []
        for i, it in enumerate(items):
            candidate_id = f"{self.correlation_id}-w{i}"
            self._emit(candidate_id, it)
            emitted.append(candidate_id)
        if emitted:
            # Emit the pick-question so the operator's selection reuses the question_answered seam (no separate
            # selection event). `devharness work-items select <id>` answers this with the chosen candidate_id.
            listing = "; ".join(f"{cid}: {it['title']}" for cid, it in zip(emitted, items))
            self.event_bus.emit_sync("question_asked", msgspec.to_builtins(QuestionAsked(
                research_id=self.correlation_id, question_id=f"{self.correlation_id}-pick",
                question_text=f"Which work item to build? Reply with a candidate_id. Candidates: {listing}",
            )), correlation_id=self.correlation_id)
        # §S9 per-role spend (rev 0.3.56). Zero-cost (mocked) runs emit nothing.
        if self.total_cost_usd > 0:
            self.event_bus.emit_sync(
                "cost_spent",
                {"role": "discovery", "amount_usd": self.total_cost_usd, "model": self.model,
                 "spent_at_millis": self._now_millis(), "correlation_id": self.correlation_id},
                correlation_id=self.correlation_id,
            )
        return emitted

    def _options(self) -> "sdk.ClaudeAgentOptions":
        return sdk.ClaudeAgentOptions(
            setting_sources=[], mcp_servers=self._mcp_server_configs, cwd=self.target_repo,
            model=self.model, allowed_tools=_READ_TOOLS, disallowed_tools=_DISALLOWED_WRITE_EXEC,
            permission_mode="bypassPermissions",  # autonomous read-only session; containment is the tool allowlist
        )

    async def _analyze(self, summary) -> str:
        """Run the read-only analysis session; return the model's final text (the JSON candidate list)."""
        from devharness.sdk_query import run_query  # overage auth-fallback (rev 0.4.0)
        result = None
        async for message in run_query(self._query_fn, self._prompt(summary), self._options()):
            cost = getattr(message, "total_cost_usd", None)
            if cost is not None:
                self.total_cost_usd += float(cost)
                result = message
        return getattr(result, "result", "") if result is not None else ""

    def _prompt(self, summary) -> str:
        return (
            "You are analyzing the software repository at the current working directory — READ-ONLY, do not "
            "modify anything. Read its code with the Read/Grep/Glob tools and identify up to "
            f"{self.max_candidates} concrete, valuable candidate work items: real improvements, gaps, or "
            "issues that FIT this codebase and add behaviour/value it lacks. Prefer well-scoped, "
            "independently-buildable items over sweeping rewrites.\n\n"
            f"Repository structure (a read-only scan):\n{summary}\n\n"
            'Return ONLY a JSON array, no prose. Each element: {"title": <short str>, "description": '
            '<precise, buildable str>, "rationale": <why it is worth doing>, "kind": one of '
            '["feature","bugfix","refactor","test_gap","dependency"], "scope_hint": [<repo-relative path globs>]}.'
        )

    def _emit(self, candidate_id, it) -> None:
        struct = WorkItemCandidate(
            correlation_id=self.correlation_id, candidate_id=candidate_id, title=it["title"],
            description=it["description"], rationale=it.get("rationale", ""), kind=it["kind"],
            scope_hint=it.get("scope_hint", []), target_repo=self.target_repo, source="llm",
            created_at_millis=self._now_millis(),
        )
        self.event_bus.emit_sync("work_item_candidate", msgspec.to_builtins(struct),
                                 correlation_id=self.correlation_id)
