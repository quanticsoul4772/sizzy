# devharness web control panel — VPS deploy

Drive the whole devharness loop from a browser (phone included) at
`https://your-host.example.com/panel/`. Plain systemd service on the VPS (`<user>@<vps-host>`),
behind the box's existing Caddy (TLS + basic auth). No containers, no sidecar — the panel is
self-contained (it serves its own UI page and a `/events` progress tail).

> **Operator-specific:** `bootstrap.sh` builds the `parallax` + `mcp-reasoning` MCP servers the write
> loop requires; `mcp-parallax` is not a public repository, so this deploy is a template — substitute
> your own builds/paths for the MCP servers and your own devharness clone URL.

## Prerequisites (already true on this box)

- Node + the `claude` CLI **logged in** via the Claude subscription under `$HOME/.claude` (the
  panel's four roles bill through it; it clears `ANTHROPIC_API_KEY`). Check: `claude` runs and is
  authenticated as the service user.
- `/etc/credstore/{anthropic-key,voyage-key}.encrypted` present (the MCP servers' own API keys).

## One-time provision

Run **on the box as the service user**, with the two MCP keys sourced from the credstore:

```bash
export ANTHROPIC_API_KEY="$(sudo systemd-creds decrypt /etc/credstore/anthropic-key.encrypted -)"
export VOYAGE_API_KEY="$(sudo systemd-creds decrypt /etc/credstore/voyage-key.encrypted -)"
# your own clone URLs — bootstrap.sh fails closed if any is unset (the repos are not bundled here):
export DEVHARNESS_REPO_URL="<your devharness clone URL>"
export DEVHARNESS_PARALLAX_REPO_URL="<your mcp-parallax clone URL>"
export DEVHARNESS_MCP_REASONING_REPO_URL="<your mcp-reasoning clone URL>"
bash ~/devharness/deploy/vps/bootstrap.sh     # (git clone the repo first if it isn't there yet)
```

`bootstrap.sh` installs apt + Rust prereqs, builds `mcp-parallax` + `mcp-reasoning` (the first z3 build
is ~5 min), installs devharness in a venv, and merges the two MCP servers into `~/.claude.json`
(top-level `mcpServers`, absolute `DATABASE_PATH`s, keys baked in — the devharness posture; the keys
never reach the systemd unit's environment).

## Install the service + Caddy route

```bash
sudo cp ~/devharness/deploy/vps/devharness-panel.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now devharness-panel
systemctl status devharness-panel            # active; loopback :8090
curl -s 127.0.0.1:8090/state | jq .next_hint # sanity

# add the Caddy route (basic auth is mandatory — the panel can drive builds)
caddy hash-password --plaintext 'YOUR_STRONG_PASSWORD'   # -> paste into the snippet
sudoedit /etc/caddy/Caddyfile                # add deploy/vps/Caddyfile.snippet inside the site block
sudo systemctl reload caddy
```

## Use it

Open `https://your-host.example.com/panel/` on your phone (basic auth). The header shows the `→ next`
hint; the panes drive the loop: **Project** (set a build target / new project / switch), **Research**
(seed + answer the interview), **Drive** (sign / plan / build next / certify / integrate / assemble),
and a live **Progress** log. One build step runs at a time (single-flight); the page polls state +
progress every 1.5 s.

## Notes

- **One writer.** The panel is the sole event-writer; all emits serialize through one lock. Drive from
  a single browser at a time (two tabs both polling is fine; two *builds* can't overlap — the second
  gets a busy 409).
- **Host-shell builds.** `DEVHARNESS_ALLOW_HOST_SHELL=1` runs the developer worker's shell/tests on the
  box (these are your own trusted build tasks).
- **Restarting:** avoid `systemctl restart` while a build is running — a stranded write lock blocks
  future dispatches (`TimeoutStopSec=180` gives an in-flight step's cleanup time to release it).
- **Host header (rev 0.4.15 request gate).** The panel rejects (403) any request whose `Host` is
  neither loopback nor `DEVHARNESS_PANEL_PUBLIC_HOST` — set that env in the systemd unit to your
  public domain. The reverse proxy MUST forward the ORIGINAL `Host` header: Caddy's `reverse_proxy`
  does by default; nginx's default rewrites it to the upstream address (every external request would
  then present a loopback Host and the gate's purpose is defeated) — use
  `proxy_set_header Host $host;`. A non-loopback `DEVHARNESS_PANEL_ADDR` bind rejects **all**
  requests — the UI page load and `/events` polling included, not just POSTs — until `PUBLIC_HOST`
  names that host. The gate is CSRF/DNS-rebinding protection only: same-box processes still reach
  the loopback bind unauthenticated (the pre-existing accepted posture — authentication is the
  reverse proxy's job).
- **Linux is free of** the Windows `core.fsmonitor` daemon-leak footgun.
- Update: `cd ~/devharness && git pull && ~/devharness/.venv/bin/pip install -e runtime && sudo systemctl restart devharness-panel` (when idle).
  If the clone's remote ever changes history (e.g. repointing at a fresh-history public mirror),
  `git pull --ff-only` can no longer fast-forward — re-clone or `git fetch && git reset --hard
  origin/main` instead; staying on the original remote keeps this flow unchanged.
