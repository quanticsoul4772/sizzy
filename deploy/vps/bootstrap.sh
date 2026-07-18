#!/usr/bin/env bash
# Provision the devharness web control panel on the VPS (Ubuntu 24.04) — run ON the box as the
# service user. NOTE operator-specific: the MCP-server clone below assumes access to mcp-parallax
# (not a public repo) — substitute your own MCP builds; set DEVHARNESS_REPO_URL to your clone URL.
# Idempotent: safe to re-run. It builds the two Rust MCP servers, installs devharness in a venv, and
# writes the parallax + mcp-reasoning entries into ~/.claude.json.
#
# Requires a VALID ANTHROPIC_API_KEY (and VOYAGE_API_KEY) in the environment. A headless box has no
# interactive `claude` login, so BOTH the MCP servers AND the four roles authenticate via the API key
# (verified: the box's subscription OAuth is not usable headless). The MCP servers read it from
# ~/.claude.json's per-server env (baked below); the panel reads it from a systemd LoadCredentialEncrypted
# credential at runtime (server._resolve_auth). Source the keys from the credstore — note --name= is
# required (the embedded credential name must match):
#   export ANTHROPIC_API_KEY="$(sudo systemd-creds decrypt --name=anthropic-key /etc/credstore/anthropic-key.encrypted -)"
#   export VOYAGE_API_KEY="$(sudo systemd-creds decrypt --name=voyage-key /etc/credstore/voyage-key.encrypted -)"
set -euo pipefail

HOME_DIR="${HOME:?HOME must be set}"
DEVH="$HOME_DIR/devharness"
MCP="$HOME_DIR/mcp"
VAR="$DEVH/var"
: "${ANTHROPIC_API_KEY:?source ANTHROPIC_API_KEY from /etc/credstore before running (see header)}"
: "${VOYAGE_API_KEY:?source VOYAGE_API_KEY from /etc/credstore before running (see header)}"

echo "==> apt prereqs"
sudo apt-get update -qq
sudo apt-get install -y build-essential cmake clang lld libssl-dev pkg-config git \
  python3-venv python3-pip curl ca-certificates jq python-is-python3 python3-pytest
#   cmake + C++  -> parallax's bundled z3   ·   clang/lld + libssl -> mcp-reasoning
#   python3-venv -> 24.04 omits venv from base python3 and PEP 668 blocks a bare pip install
#   python-is-python3 -> Ubuntu has no `python`; the verifier's `python -m pytest` needs it (else the
#   build dies at verify with FileNotFoundError). python3-pytest -> pytest for that `python`.

# A git identity so the developer's checkpoint/scratch/assemble commits never hit `git commit` exit 128
# on a box with no configured identity (the checkpoint sets one inline since rev 0.3.86, but a global
# is the belt-and-braces + covers any other git op).
git config --global user.name  >/dev/null 2>&1 || git config --global user.name  "devharness"
git config --global user.email >/dev/null 2>&1 || git config --global user.email "devharness@$(hostname -f 2>/dev/null || hostname)"

echo "==> Rust (>=1.94, both crates' MSRV)"
if ! command -v cargo >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi
# shellcheck disable=SC1091
source "$HOME_DIR/.cargo/env"

echo "==> build the MCP servers (parallax's first z3 build is ~5 min)"
# Clone URLs are operator-supplied (the MCP servers are separate repos, not bundled here) — set
# both env vars to your own clone URLs; fail-closed like DEVHARNESS_REPO_URL above.
mkdir -p "$MCP"
: "${DEVHARNESS_PARALLAX_REPO_URL:?set DEVHARNESS_PARALLAX_REPO_URL to your mcp-parallax clone URL}"
: "${DEVHARNESS_MCP_REASONING_REPO_URL:?set DEVHARNESS_MCP_REASONING_REPO_URL to your mcp-reasoning clone URL}"
for pair in "mcp-parallax:$DEVHARNESS_PARALLAX_REPO_URL" "mcp-reasoning:$DEVHARNESS_MCP_REASONING_REPO_URL"; do
  repo="${pair%%:*}"; url="${pair#*:}"
  [ -d "$MCP/$repo/.git" ] || git clone "$url" "$MCP/$repo"
  ( cd "$MCP/$repo" && git pull --ff-only && cargo build --release )
done
PARALLAX="$MCP/mcp-parallax/target/release/mcp-parallax"
REASONING="$MCP/mcp-reasoning/target/release/mcp-reasoning"
[ -x "$PARALLAX" ] && [ -x "$REASONING" ] || { echo "MCP build failed"; exit 1; }

echo "==> install devharness"
[ -d "$DEVH/.git" ] || git clone "${DEVHARNESS_REPO_URL:?set DEVHARNESS_REPO_URL to your devharness clone URL}" "$DEVH"
( cd "$DEVH" && git pull --ff-only )
[ -d "$DEVH/.venv" ] || python3 -m venv "$DEVH/.venv"
"$DEVH/.venv/bin/pip" install -q --upgrade pip
"$DEVH/.venv/bin/pip" install -q -e "$DEVH/runtime"
mkdir -p "$VAR"

echo "==> merge parallax + mcp-reasoning into ~/.claude.json (top-level mcpServers; absolute DB paths)"
CJ="$HOME_DIR/.claude.json"
[ -f "$CJ" ] || echo '{}' > "$CJ"
tmp="$(mktemp)"
jq --arg px "$PARALLAX" --arg rx "$REASONING" --arg ak "$ANTHROPIC_API_KEY" --arg vk "$VOYAGE_API_KEY" \
   --arg pdb "$VAR/parallax.db" --arg rdb "$VAR/reasoning.db" '
  .mcpServers = (.mcpServers // {})
  | .mcpServers.parallax = {command:$px, args:[],
      env:{ANTHROPIC_API_KEY:$ak, VOYAGE_API_KEY:$vk, DATABASE_PATH:$pdb, LOG_LEVEL:"info"}}
  | .mcpServers["mcp-reasoning"] = {command:$rx, args:[],
      env:{ANTHROPIC_API_KEY:$ak, VOYAGE_API_KEY:$vk, DATABASE_PATH:$rdb, LOG_LEVEL:"info"}}
  ' "$CJ" > "$tmp" && mv "$tmp" "$CJ"
chmod 600 "$CJ"
# GROUNDED_VERIFY_ROOT deliberately unset (unset -> the grounded_verify tool is simply absent, which
# devharness doesn't use; set-but-invalid would boot-fail parallax).

echo "==> smoke: the binaries run + parse their env"
"$PARALLAX" --help >/dev/null 2>&1 || echo "  (parallax --help nonzero — check ANTHROPIC_API_KEY)"
"$REASONING" --version >/dev/null 2>&1 || echo "  (mcp-reasoning --version nonzero)"

echo
echo "Done. Next:"
echo "  1. sudo cp $DEVH/deploy/vps/devharness-panel.service /etc/systemd/system/"
echo "  2. sudo systemctl daemon-reload && sudo systemctl enable --now devharness-panel"
echo "  3. add deploy/vps/Caddyfile.snippet to /etc/caddy/Caddyfile, then: sudo systemctl reload caddy"
echo "  4. browse https://your-host.example.com/panel/  (basic auth)"
