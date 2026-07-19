"""Advisory-lite — the bundled substitute MCP server (rev 0.4.26).

``python -m devharness.advisory --tools parallax|reasoning`` serves the minimal tool surface the
private parallax / mcp-reasoning servers provide (the contract in docs/local-mcp-setup.md), so an
outside user runs the full write loop with only Claude Code installed. Wired purely via
``DEVHARNESS_MCP_CONFIG`` — the harness's tool namespace (``mcp__parallax__verify``) comes from the
config KEY, so this server slots in with zero harness wiring changes.

What it is, stated plainly: verification here is a SINGLE-PASS LLM judgment (nonce-guarded, with a
server-constructed canonical verdict — see prompts.py), not real parallax's multi-pass adversarial
ensemble. It restores feature/OSS task completion (``verify`` is loop-blocking — the spec_claim /
spec_criteria axes fail closed in both the verifier and the fresh reviewer) and raises the
research / non-goals / retro quality floor above the built-in heuristics. Its nested SDK sessions
bill the same login additively, invisible to SC-6 cost events (the inner session's cost never
reaches the relay's ResultMessage).

Handler discipline: no stdout writes anywhere in this package (stdout IS the MCP protocol; stderr
only); optional params are ``str | None`` (the research role passes ``context=None`` on round 1 —
a pydantic rejection would burn the shape-gate's one structural retry and degrade every interview);
verdict tools register ``structured_output=False`` (FastMCP's structured wrapping would put
``{"result": "<text>"}`` on the wire — ``result`` is a harness verdict key and the full-sentence
value is not a pass-word, so a genuine supported verdict could fail closed on a relay echo).
"""

import json

from devharness.advisory import llm
from devharness.advisory.prompts import (
    check_prompt,
    diverge_prompt,
    elicit_prompt,
    grounded_prompt,
    new_nonce,
    parse_nonce_verdict,
    render_verdict,
    read_sources,
    sanitize,
    verify_prompt,
)

_ELICIT_ERROR = "advisory elicit produced no valid divergence payload"  # fixed text, deliberately brace-free


async def _verdict_call(build_prompt, nonce: str) -> str:
    text = await llm._complete(build_prompt)
    ok = parse_nonce_verdict(text, nonce)
    return render_verdict(ok, rationale=text if ok is False else "")


def _valid_elicit_payload(text: str):
    """Parse + validate the elicit JSON; return the normalized payload dict or None."""
    try:
        start = text.index("{")
        end = text.rindex("}")
        payload = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or "divergence_points" not in payload:
        return None
    points = payload.get("divergence_points")
    if not isinstance(points, list):
        return None
    clean_points = []
    for p in points[:3]:
        if isinstance(p, dict) and p.get("question"):
            clean_points.append({"question": str(p["question"]), "signal": str(p.get("signal", ""))})
    if points and not clean_points:
        # review catch: a non-empty list whose points all lack a usable "question" is a MALFORMED
        # generation (the wrong-key class the retry exists for), not "no divergence" — returning []
        # here would silently terminate the interview with zero questions asked
        return None
    return {
        "assumed_objective": str(payload.get("assumed_objective", "")),
        "signal_level": "low" if str(payload.get("signal_level", "")).lower() == "low" else "high",
        "divergence_points": clean_points,
    }


def build_app(toolset: str):
    """The FastMCP app for one toolset ('parallax' or 'reasoning'). The server's own name is
    cosmetic — the harness's tool namespace comes from the DEVHARNESS_MCP_CONFIG key."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP(f"devharness-advisory-{toolset}")

    if toolset == "parallax":

        @app.tool(structured_output=False)
        async def verify(claim: str, context: str | None = None) -> str:
            """Verify a claim (advisory-lite single-pass judgment)."""
            nonce = new_nonce()
            return await _verdict_call(verify_prompt(claim, context or "", nonce), nonce)

        @app.tool(structured_output=False)
        async def check(claim: str) -> str:
            """Check a computable claim (advisory-lite single-pass judgment)."""
            nonce = new_nonce()
            return await _verdict_call(check_prompt(claim, nonce), nonce)

        @app.tool(structured_output=False)
        async def grounded_verify(claim: str, sources: list[str] | None = None) -> str:
            """Verify a claim strictly against named source files/ranges."""
            if not sources:
                # matching real parallax: an empty source set REFUSES (accepting would weaken the
                # reviewer gate); "no repository artifacts" is a harness refutation anchor
                return json.dumps({"verdict": "refuted",
                                   "detail": "not supported — no repository artifacts named"})
            text, unreadable = read_sources(sources)
            if unreadable is not None:
                return json.dumps({"verdict": "refuted",
                                   "detail": f"not supported — source could not be read: {unreadable}"})
            nonce = new_nonce()
            return await _verdict_call(grounded_prompt(claim, text, nonce), nonce)

        @app.tool(structured_output=False)
        async def elicit(task: str, context: str | None = None) -> str:
            """One interview round: the divergence-points payload (advisory-lite)."""
            for _ in range(2):  # one internal retry on a malformed generation
                text = await llm._complete(elicit_prompt(task, context or ""))
                payload = _valid_elicit_payload(text)
                if payload is not None:
                    return json.dumps(payload)
            raise RuntimeError(_ELICIT_ERROR)

        @app.tool(structured_output=False)
        async def diverge(problem: str) -> str:
            """Alternative interpretations of a problem, as one plain-text paragraph."""
            # NOT sanitize() (review catch): that is verdict-channel hygiene — scrubbing pass-words
            # would mangle prose research folds verbatim into the spec's assumption text. Diverge
            # output feeds no verdict parser; a length cap is the only hygiene needed.
            return (await llm._complete(diverge_prompt(problem))).strip()[:600]

    elif toolset == "reasoning":
        # Static handlers, zero LLM: the director's fork sites discard these outputs entirely (the
        # budget reads the RELAY session's usage). Kwarg names match the real call sites.

        @app.tool(structured_output=False)
        async def reasoning_decision(at: str = "", spec: str = "", task_class: str = "") -> str:
            """Decision fork (advisory-lite: acknowledged; output is not consumed by the harness)."""
            return "acknowledged (advisory-lite static reasoning)"

        @app.tool(structured_output=False)
        async def reasoning_reflection(on: str = "") -> str:
            """Reflection fork (advisory-lite: acknowledged; output is not consumed)."""
            return "acknowledged (advisory-lite static reasoning)"

        @app.tool(structured_output=False)
        async def reasoning_meta() -> str:
            """Meta fork (advisory-lite: acknowledged; output is not consumed)."""
            return "acknowledged (advisory-lite static reasoning)"

    else:
        raise ValueError(f"unknown toolset: {toolset!r} (expected 'parallax' or 'reasoning')")

    return app
