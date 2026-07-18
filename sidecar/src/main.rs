//! devharness SSE sidecar entry point (B0.6).
//!
//! Config: DB path from `DEVHARNESS_DB` env or argv[1]; poll cadence from
//! `DEVHARNESS_POLL_MS` (default 500); bind address from `DEVHARNESS_SIDECAR_ADDR`
//! (default 127.0.0.1:8080).

use std::sync::atomic::{AtomicBool, AtomicI64};
use std::sync::Arc;

use sidecar::{app, spawn_poller, AppState};
use tokio::sync::broadcast;

#[tokio::main]
async fn main() {
    let db_path = std::env::var("DEVHARNESS_DB")
        .ok()
        .or_else(|| std::env::args().nth(1))
        .unwrap_or_else(|| "devharness.db".to_string());
    let poll_ms: u64 = std::env::var("DEVHARNESS_POLL_MS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(500);
    let addr =
        std::env::var("DEVHARNESS_SIDECAR_ADDR").unwrap_or_else(|_| "127.0.0.1:8080".to_string());

    let (tx, _) = broadcast::channel(1024);
    let state = AppState {
        tx,
        db_path,
        high_water: Arc::new(AtomicI64::new(0)),
        db_connected: Arc::new(AtomicBool::new(false)),
    };

    spawn_poller(state.clone(), poll_ms);

    let listener = tokio::net::TcpListener::bind(&addr).await.expect("bind");
    eprintln!("devharness sidecar listening on {addr} (db={})", state.db_path);
    axum::serve(listener, app(state)).await.expect("serve");
}
