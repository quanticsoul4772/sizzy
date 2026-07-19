# Local MCP setup — wiring parallax / mcp-reasoning (or your own substitutes)

The devharness write loop consults two operator-local MCP servers:

- **parallax** — independent verification correctives (the verifier's `verify`/`check`/
  `grounded_verify` axes, the research interview's `elicit`/`diverge`).
- **mcp-reasoning** — the director's reasoning forks and spec decomposition.

They are **separate repositories, not bundled here**, and their launch specs are operator-local and
machine-specific — the harness reads them live from configuration, never from the repo. This page is
the local (non-VPS) wiring guide: where the config lives, how to point the harness at a different
config file, and — if you don't have the original servers — the exact minimal tool surface a
substitute must provide.

## Where the config is read

All launch-spec reads go through one module, `runtime/devharness/mcp/config.py`:

1. **`DEVHARNESS_MCP_CONFIG`** (if set) — the path to any JSON file with a top-level `mcpServers`
   block. An explicitly-set override **fails closed**: a missing/invalid file or an absent server is
   an error naming the path, never a silent fallback.
2. Otherwise **`~/.claude.json`** — the Claude Code CLI's own config, top-level `mcpServers` block.
   This is what a normal Claude Code MCP registration produces, and what the VPS bootstrap writes.

A repo-local example (never commit a file containing real keys):

```bash
# mcp.local.json — gitignored, per-checkout
export DEVHARNESS_MCP_CONFIG="$PWD/mcp.local.json"
```

```json
{
  "mcpServers": {
    "parallax": {
      "command": "/path/to/your/parallax-binary",
      "args": ["--stdio"],
      "env": { "ANTHROPIC_API_KEY": "<your-key-if-the-server-needs-one>" }
    },
    "mcp-reasoning": {
      "command": "/path/to/your/mcp-reasoning-binary",
      "args": ["--stdio"],
      "env": { "ANTHROPIC_API_KEY": "<your-key-if-the-server-needs-one>" }
    }
  }
}
```

Notes:

- The harness passes each server's spec to the Claude Agent SDK as-is (`command`/`args`/`env` —
  the standard MCP stdio shape).
- The **overage fallback** (see `README.md` → Safety) sources its API key from the same config:
  the top-level `mcpServers["mcp-reasoning"].env.ANTHROPIC_API_KEY`, falling back to
  `["parallax"]` — in that order, top-level only.
- **VPS relationship:** `deploy/vps/bootstrap.sh` writes these entries into `~/.claude.json` on the
  box; `DEVHARNESS_MCP_CONFIG` is the local-machine alternative. Do **not** set it in the panel's
  systemd unit — the deployed panel service depends on the home-file key path.
- Config resolution is lazy (at dispatch time, not import time), so everything that doesn't drive
  an LLM role — tests, `sweep`, the read-only console/panel, the dashboard — runs without any of
  this being configured.

## What a substitute server must provide

If you don't have the original parallax/mcp-reasoning binaries, a substitute MCP server satisfies
every call site with a small surface. Only these tools have runtime callers:

### parallax (5 tools)

| Tool | Called with | Result the harness accepts |
|---|---|---|
| `verify` | `claim=`, `context=` (untrusted text is passed as the separate `context` param, never concatenated into the claim) | Either prose containing a line like `Verdict: **supported**` / `Verdict: **refuted**` (the first pass/fail word on the Verdict line decides), or JSON with a `verdict`/`result`/`status`/`decision` key, or a `findings` list (empty ⇒ pass). Parsed by `parallax_passed` (`runtime/devharness/verifier/builtin/_common.py`). |
| `check` | `claim=` | Same verdict shapes as `verify`. |
| `grounded_verify` | claim + named source files/ranges | Same verdict shapes. |
| `elicit` | `task=`, `context=` (the interview state) | A JSON object — validity is decided by **payload shape**, not prose: `{"divergence_points": [{"question": "…", "signal": "…"}, …], "assumed_objective": "…"}`. An empty `divergence_points` list terminates the interview. An errored or shapeless result gets one retry, then the harness falls back to template synthesis. |
| `diverge` | `problem=` | Plain text (used only as a fallback assumption string). |

### mcp-reasoning (3 tools + completions)

| Tool | Result the harness uses |
|---|---|
| `reasoning_decision`, `reasoning_reflection`, `reasoning_meta` | The **output text is discarded** — only the result's `usage` (token accounting) and error status are read at the director's fork sites. A stub that returns any well-formed result satisfies them (the shipped `run_developer` driver stubs reasoning this way; `run_oss` and the console director wire the real client, so the reasoning server must exist for those paths — a static substitute suffices). |
| (plain completion) | Spec decomposition uses a serverless SDK completion whose output **is** parsed as a JSON task list; malformed output degrades to a single-task default. (The relay session still *boots* the configured server even when no tool is called — a substitute must start fast.) |

The degradation ladder is deliberate for the *advisory* surfaces: a parallax error inside a gate
degrades to the deterministic keyword heuristic; an elicit failure degrades to template synthesis;
decomposition degrades to a single-task plan. **But `verify` is load-bearing, not advisory**: the
feature verifier's `spec_claim`/`spec_criteria` axes fail closed on an errored or unparseable
verdict — in both the first-pass verifier and the fresh-context reviewer — so **feature and OSS
tasks cannot complete without a working `verify`**. A substitute restores that completion path and
raises the quality floor everywhere else; the loop's fail-closed gates and the fresh-context
reviewer still hold independently.

## Bundled substitute: advisory-lite

The repo ships that substitute: `python -m devharness.advisory --tools parallax|reasoning` — a
FastMCP stdio server inside the runtime package (no extra dependencies; `mcp` ships with the Agent
SDK). **The shortcut: `python -m devharness init` writes the config below for you** (with the
correct absolute interpreter path), self-validates it, and prints the env lines — see
`docs/first-build.md` for the full walkthrough. Hand-writing it instead: two entries in your
`DEVHARNESS_MCP_CONFIG` file (use the absolute path of the interpreter where you ran
`pip install -e runtime` — a bare `python` may resolve to a different interpreter):

```json
{
  "mcpServers": {
    "parallax": {
      "command": "/absolute/path/to/your/python",
      "args": ["-m", "devharness.advisory", "--tools", "parallax"]
    },
    "mcp-reasoning": {
      "command": "/absolute/path/to/your/python",
      "args": ["-m", "devharness.advisory", "--tools", "reasoning"]
    }
  }
}
```

What it is, stated plainly:

- **Verification is a single-pass LLM judgment**, not real parallax's multi-pass adversarial
  ensemble. It restores feature/OSS completion and raises the research/non-goals/retro quality
  floor; it is not a substitute for parallax's independence guarantees.
- The verdict pipeline is hardened: untrusted context rides in a delimited data block, the judge
  answers through a per-call nonce sentinel, and the server re-renders a canonical one-line JSON
  verdict — the judge's raw text never reaches the harness. Residuals: the relay session may
  paraphrase, and any LLM judge can be persuaded by hostile context; the harness's injection
  pre-gates remain the primary defense.
- The judge model defaults to the T1 advisory model (family-independent of the frontier writer);
  override with `DEVHARNESS_ADVISORY_MODEL`.
- **Billing**: the nested judge sessions bill the same Claude login as the harness, additively —
  and that inner spend is **not visible in `cost_spent` events** — a documented scope exception:
  the harness's SC-6 contract binds its own clients, and this server is outside its event surface
  (SC-6 sees only the relay session). The verifier and reviewer sessions run sequentially, so the pressure is serial.
- **Latency**: the relay blocks on each tool call while the judge session runs; the CLI's MCP tool
  timeouts (`MCP_TIMEOUT`/`MCP_TOOL_TIMEOUT`) can kill slow calls, which fails closed.
- The reasoning-side server is static (no LLM) — the director's fork outputs are discarded by
  design, and decomposition runs as a plain completion in the relay session.

Live validation: `DEVHARNESS_RUN_ADVISORY_LIVE=1 pytest tests/runtime/test_advisory_live.py`
drives a hermetic feature build end-to-end through the bundled server (verifier + fresh reviewer
both) — a completed terminal is the proof. It spends real money.
