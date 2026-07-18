# sidecar/ — the Rust SSE relay

A small, read-only Rust service that tails the SQLite event log and multiplexes it to the dashboard over
Server-Sent Events. See the [project README](../README.md) for the big picture.

## What it does

- Tails the append-only `events` table (via bundled `rusqlite`) and relays new events to subscribers.
- Serves a single CORS-enabled `/events/all` SSE stream — the dashboard opens **one** long-lived
  connection and demuxes by `event_type` client-side (the browser's ~6-connections-per-host limit makes a
  per-tile connection design starve later tiles).
- Built on **axum** + **tokio** (chosen for first-class SSE on tokio/hyper). It is read-only: the runtime
  is the sole writer to the event log.

## Build & test

```bash
cargo build --release      # binary: target/release/sidecar
cargo test                 # 6 tests
```

## Run

```bash
./target/release/sidecar
```

Then start the dashboard (`cd ../dashboard && npm run dev`). To tear the dev stack down, kill
`sidecar.exe` and the vite PID **by port** — never blanket-kill `node.exe` (see
[`../CONTRIBUTING.md`](../CONTRIBUTING.md), dev-stack teardown).
