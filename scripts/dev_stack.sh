#!/usr/bin/env bash
# Dev-stack launcher for the dashboard browser verify (Track 4 of operator-infra-plan.md).
# Builds the Rust sidecar, starts it + vite against an event DB, prints the URLs. `--down` tears the
# stack down. Reproducible replacement for the ad-hoc stand-up that bit the B1.7–B5.7 render attempts.
#
# 🔴 TEARDOWN INVARIANT: never `taskkill //IM node.exe //F` — the Playwright MCP server itself runs as a
# node.exe process, so a blanket node kill drops the MCP mid-verify. Tear down by sidecar.exe image + the
# vite PID *by port* only.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DB="${DEVHARNESS_DB:-$REPO/var/devharness.db}"
ADDR="${DEVHARNESS_SIDECAR_ADDR:-127.0.0.1:8080}"
VITE_PORT="${VITE_PORT:-5173}"

down() {
  taskkill //IM sidecar.exe //F >/dev/null 2>&1 || true
  local pid
  # anchor the port (":5173" followed by whitespace) so it can't match :51730… or a foreign address
  pid="$(netstat -ano 2>/dev/null | grep -E ":$VITE_PORT[[:space:]]" | grep LISTENING | awk '{print $NF}' | head -1)"
  if [ -n "${pid:-}" ]; then taskkill //PID "$pid" //F >/dev/null 2>&1 || true; fi
  echo "dev-stack down (sidecar.exe + vite :$VITE_PORT killed; node.exe left untouched)"
}

if [ "${1:-}" = "--down" ]; then down; exit 0; fi

[ -f "$DB" ] || { echo "no event DB at $DB (set DEVHARNESS_DB to a seeded DB)"; exit 1; }

echo "==> building sidecar (release)"
( cd "$REPO/sidecar" && cargo build --release ) || { echo "sidecar build failed"; exit 1; }

mkdir -p "$REPO/var"
echo "==> starting sidecar on $ADDR (db=$DB)"
DEVHARNESS_DB="$DB" DEVHARNESS_SIDECAR_ADDR="$ADDR" \
  "$REPO/sidecar/target/release/sidecar.exe" >"$REPO/var/sidecar.log" 2>&1 &

echo "==> starting vite on :$VITE_PORT"
( cd "$REPO/dashboard" && npm run dev -- --port "$VITE_PORT" --strictPort >"$REPO/var/vite.log" 2>&1 & )

sleep 4
echo "----"
echo "dashboard : http://localhost:$VITE_PORT"
echo "sidecar   : http://$ADDR/health"
echo "logs      : var/sidecar.log  var/vite.log"
echo "teardown  : scripts/dev_stack.sh --down   (never taskkill node.exe)"
