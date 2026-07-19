# Your first build — from clone to a working CLI, with no private servers

This is the worked path from a fresh clone to a finished, tested artifact built by the harness's
own loop, using the bundled **advisory-lite** substitute — no private MCP servers required. It
follows a real reference build (a stdlib character/word-frequency CLI: two interview rounds, a
signed spec, a six-task plan, every task completed with the verifier catching and auto-retrying two
wrong claims along the way).

Commands use the `python -m` form throughout — it always runs under the interpreter that owns your
editable install, which matters here because the config you generate embeds that interpreter's
path. (The installed `devharness` script is equivalent shorthand *if* your Scripts directory is on
PATH.)

## 1. Install and see it work

From the repo root (note: `pip install .` at the root installs the bundled **jqlite** demo, not the
harness — the harness installs from `runtime/`):

```bash
cd runtime && pip install -e ".[test,tui]" && cd ..
pytest tests/runtime -q -n auto      # the see-it-work step: the full suite runs with no servers, no keys
```

## 2. Wire advisory-lite (one command)

```bash
python -m devharness init
```

This writes `mcp.local.json` (gitignored at the repo root) pointing both MCP server names at the
bundled substitute, self-validates it, and prints the two environment lines for your shell —
PowerShell and bash forms. Set them in the shell you'll drive from. That's the whole wiring.

If you have the real parallax/mcp-reasoning servers, edit the written `command`/`args` instead —
see `docs/local-mcp-setup.md`.

## 3. Drive the loop

```bash
python -m devharness.console
```

The console is a keyboard-driven TUI: a live state panel, a progress log, and the keymap in the
footer. The whole loop is these keys:

| Key | Step | What happens |
|---|---|---|
| `N` | New project | Prompted for `name \| repo_path \| seed idea`. A relative repo path like `../myproject` works — the directory is created and git-initialized, and a fresh per-project event store appears under `var/`. Give the seed one concrete sentence: *"a stdlib-only CLI that reports character and word frequency statistics for text files"*. |
| `R` | Research | The interview starts. Advisory-lite reads your seed and asks about the points where reasonable interpretations genuinely diverge — output format? tokenization rules? error handling? Expect **typically 2–3 rounds (hard cap 5)**; a crisp seed sometimes gets a single confirmation turn. |
| `A` | Answer | Type one answer covering every numbered point in the round. Settled points aren't re-asked. |
| `v` then `s` | Review + sign | The synthesized spec renders in a viewer — this is your gate. It should reflect your answers; sign it (`s`) or reject it (`x`) and re-run research. Nothing builds until you sign. |
| `D` | Plan | The director decomposes the signed spec into an ordered, dependency-linked task plan (the reference build got six tasks from one seed sentence). |
| `W` | Build | One task per press: the developer writes in an isolated worktree, the verifier checks the realized diff against the spec claim, and a fresh-context reviewer certifies independently — **done is earned twice**. When the verifier *refuses* a claim, that's the system working: the task rewinds and retries with the refutation in context. The reference build hit two refusals and self-corrected both. The learning spine analyzes each finished task automatically. |
| `M` / `i` | Assemble / integrate | Merge the completed task branches; your artifact is ready to run in the repo you named. |

## 4. What to expect

- **Time**: minutes per task — the verifier and reviewer each run a judge session, sequentially.
- **Cost**: billed to your Claude login. Advisory-lite's nested judge sessions roughly **double** a
  task's LLM cost versus a build with the real servers — budget a few dollars per task, so a
  multi-task first build lands in the tens of dollars. The console's `$` key shows the per-role
  ledger live.
- **Quality posture, stated plainly**: advisory-lite verification is a single-pass LLM judgment,
  not the real parallax multi-pass ensemble. The loop's structural guarantees (fail-closed gates,
  done-earned-twice, scope enforcement on the realized diff) hold regardless of which server
  answers.
- Driving from a phone instead: the web panel exposes the same loop — see
  `docs/operator-console-guide.md`.

## 5. When something goes wrong

| Symptom | Cause / fix |
|---|---|
| `parallax not found under mcpServers …` | `DEVHARNESS_MCP_CONFIG` isn't set **in this shell** — re-run the two lines `init` printed. |
| An SDK session dies instantly (`exit code 1`) | A stray `ANTHROPIC_API_KEY` in your machine/user environment kills the CLI at launch. The console clears it automatically at startup, but your own scripts won't — unset it, or let the console do the driving. |
| A judge call killed mid-verify | The Claude CLI's MCP tool timeouts (`MCP_TIMEOUT` / `MCP_TOOL_TIMEOUT`) cut a slow nested session; the verifier fails closed and the task retries. Raise the env knobs if it recurs. |
| `event-store directory does not exist …` | A relative `DEVHARNESS_DB` resolves against your current directory and fails closed naming the resolved path — run from the repo root, or use an absolute path. (With the variable unset, the default store location is independent of your cwd.) |

The loop is deliberately operator-gated: the interview answers, the spec signature, and integration
are yours. Everything else — writing, verifying, reviewing, learning — is the harness's job.
