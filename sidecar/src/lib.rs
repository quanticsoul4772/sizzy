//! devharness SSE sidecar (B0.6).
//!
//! Read-only tail of the SQLite event log. A poller thread reads rows past a
//! high-water `seq` and broadcasts each new event; axum SSE endpoints subscribe
//! to the broadcast and filter per channel. Read-only by construction — the
//! sidecar never writes the event store (single-writer invariant).
//!
//! Adopt-from-birth lessons wired here (brief lines 187-191):
//!   L7  `events_schema_ok` — schema-compat check of the SQL the sidecar runs.
//!   L8  degraded-state poller (`spawn_poller`) + read-only open (`open_db`):
//!       the sidecar is a separate process and survives the DB being absent.
//!   L10 `dead_event_types` — audits catalog event types that have never fired.
//!   L9/L11 are scaffolding only in B0 (no agent tools/gates produce traffic yet);
//!       the dead-event audit is the seed the L11 "never-fired surfaces as a
//!       review candidate" mechanism builds on.

use std::convert::Infallible;
use std::sync::atomic::{AtomicBool, AtomicI64, Ordering::Relaxed};
use std::sync::Arc;
use std::time::Duration;

use axum::extract::{Path, State};
use axum::http::header;
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use rusqlite::{Connection, OpenFlags};
use tokio::sync::broadcast;
use tower_http::cors::CorsLayer;
use tokio_stream::wrappers::BroadcastStream;
use tokio_stream::{Stream, StreamExt};

// The event-type catalog — GENERATED from runtime/devharness/events/registry.py via
// runtime/devharness/events/manifest.py (`python -m devharness.events.manifest`). Was hand-frozen at
// 7 of 49 types (#H9), which neutered the dead-event audit for 42 types; CI guards drift
// (test_event_catalog_rs_derived.py). Defines `pub const EVENT_CATALOG: &[&str]`.
include!("event_catalog.generated.rs");

/// One event broadcast from the poller to the SSE handlers.
#[derive(Clone, Debug)]
pub struct EventMsg {
    pub seq: i64,
    pub event_type: String,
    pub payload: String,
}

impl EventMsg {
    /// SSE data body. `payload` is already a JSON string from the event store. `replayed` marks
    /// backlog events sent on connect (vs. live) so the dashboard times only live events — the
    /// event store records no wall-clock time, so a replayed event has no recoverable real time.
    pub fn to_json(&self, replayed: bool) -> String {
        // event_type is JSON-escaped (defensive: today every type name is an identifier, but a future
        // type carrying a quote or backslash would otherwise emit malformed JSON). payload is already a
        // JSON string from the event store and is passed through verbatim.
        let etype = self.event_type.replace('\\', "\\\\").replace('"', "\\\"");
        format!(
            r#"{{"seq":{},"event_type":"{}","replayed":{},"payload":{}}}"#,
            self.seq, etype, replayed, self.payload
        )
    }
}

/// Shared HTTP state.
#[derive(Clone)]
pub struct AppState {
    pub tx: broadcast::Sender<EventMsg>,
    pub db_path: String,
    pub high_water: Arc<AtomicI64>,
    pub db_connected: Arc<AtomicBool>,
}

/// Open the event store read-only. Fails (degraded, L8) if the file is absent.
pub fn open_db(path: &str) -> rusqlite::Result<Connection> {
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
}

/// L7: the columns the sidecar's SQL depends on exist in `events`.
pub fn events_schema_ok(conn: &Connection) -> rusqlite::Result<bool> {
    let required = ["seq", "event_type", "payload"];
    let mut stmt = conn.prepare("PRAGMA table_info(events)")?;
    let cols: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(1))?
        .collect::<rusqlite::Result<_>>()?;
    Ok(required.iter().all(|c| cols.iter().any(|x| x == c)))
}

/// Read events with `seq > high_water`, broadcast each, return the new high-water.
pub fn poll_once(
    conn: &Connection,
    high_water: i64,
    tx: &broadcast::Sender<EventMsg>,
) -> rusqlite::Result<i64> {
    let mut stmt =
        conn.prepare("SELECT seq, event_type, payload FROM events WHERE seq > ?1 ORDER BY seq")?;
    let rows = stmt.query_map([high_water], |r| {
        Ok(EventMsg {
            seq: r.get(0)?,
            event_type: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
            payload: r.get::<_, Option<String>>(2)?.unwrap_or_else(|| "null".to_string()),
        })
    })?;
    let mut hw = high_water;
    for row in rows {
        let msg = row?;
        hw = msg.seq;
        let _ = tx.send(msg); // Err only means no live subscribers — fine.
    }
    Ok(hw)
}

/// Read the existing event history (channel-filtered) for replay when a client connects, plus the
/// global max `seq` at read time. A fresh SSE client must see past events, not just ones that fire
/// after it connects; the live stream then skips anything with `seq <= max_seq` so the replayed
/// history is never re-sent.
pub fn backlog(conn: &Connection, channel: &str) -> rusqlite::Result<(Vec<EventMsg>, i64)> {
    let mut stmt =
        conn.prepare("SELECT seq, event_type, payload FROM events ORDER BY seq")?;
    let rows = stmt.query_map([], |r| {
        Ok(EventMsg {
            seq: r.get(0)?,
            event_type: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
            payload: r.get::<_, Option<String>>(2)?.unwrap_or_else(|| "null".to_string()),
        })
    })?;
    let mut out = Vec::new();
    let mut max_seq = 0i64;
    for row in rows {
        let msg = row?;
        max_seq = msg.seq; // ORDER BY seq -> the last row carries the global max
        if channel_matches(channel, &msg.event_type) {
            out.push(msg);
        }
    }
    Ok((out, max_seq))
}

/// L10: catalog event types that have never appeared in the log.
pub fn dead_event_types(conn: &Connection) -> rusqlite::Result<Vec<String>> {
    let mut present = std::collections::HashSet::new();
    let mut stmt = conn.prepare("SELECT DISTINCT event_type FROM events")?;
    let rows = stmt.query_map([], |r| r.get::<_, Option<String>>(0))?;
    for row in rows {
        if let Some(t) = row? {
            present.insert(t);
        }
    }
    Ok(EVENT_CATALOG
        .iter()
        .filter(|t| !present.contains(**t))
        .map(|t| t.to_string())
        .collect())
}

/// A channel matches an event type when it is "all" or equals the type.
pub fn channel_matches(channel: &str, event_type: &str) -> bool {
    channel == "all" || channel == event_type
}

/// The exact filter the SSE endpoints apply, exposed for testing.
pub fn filtered_messages(
    msgs: impl IntoIterator<Item = EventMsg>,
    channel: &str,
) -> Vec<EventMsg> {
    msgs.into_iter()
        .filter(|m| channel_matches(channel, &m.event_type))
        .collect()
}

/// SSE stream for one channel: filtered broadcast events as SSE messages. `after_seq` skips events
/// the replay backlog already sent (0 = no replay, stream everything).
pub fn sse_stream(
    rx: broadcast::Receiver<EventMsg>,
    channel: String,
    after_seq: i64,
) -> impl Stream<Item = Result<Event, Infallible>> {
    BroadcastStream::new(rx).filter_map(move |res| match res {
        Ok(msg) if msg.seq > after_seq && channel_matches(&channel, &msg.event_type) => {
            Some(Ok(Event::default()
                .event(msg.event_type.clone())
                .data(msg.to_json(false))))
        }
        _ => None, // drop already-replayed events, non-matching events, and lag errors
    })
}

async fn sse_channel(
    State(st): State<AppState>,
    Path(channel): Path<String>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    // Subscribe to the live broadcast BEFORE reading the backlog, so an event committed during the
    // read is never lost (it arrives via live; the after_seq filter de-dups it if it was replayed).
    let rx = st.tx.subscribe();
    let (history, after_seq) = match open_db(&st.db_path) {
        Ok(conn) => backlog(&conn, &channel).unwrap_or_default(),
        Err(_) => (Vec::new(), 0),
    };
    let replay = tokio_stream::iter(history.into_iter().map(|m| {
        Ok(Event::default().event(m.event_type.clone()).data(m.to_json(true)))
    }));
    let live = sse_stream(rx, channel, after_seq);
    Sse::new(replay.chain(live)).keep_alive(KeepAlive::default())
}

async fn health(State(st): State<AppState>) -> impl IntoResponse {
    let connected = st.db_connected.load(Relaxed);
    let body = format!(
        r#"{{"db_connected":{},"degraded":{},"high_water":{}}}"#,
        connected,
        !connected,
        st.high_water.load(Relaxed)
    );
    ([(header::CONTENT_TYPE, "application/json")], body)
}

async fn dead_events(State(st): State<AppState>) -> impl IntoResponse {
    let body = match open_db(&st.db_path) {
        Ok(conn) => {
            let dead = dead_event_types(&conn).unwrap_or_default();
            let items: Vec<String> = dead.iter().map(|t| format!("\"{t}\"")).collect();
            format!(r#"{{"dead_event_types":[{}]}}"#, items.join(","))
        }
        Err(_) => r#"{"dead_event_types":[],"degraded":true}"#.to_string(),
    };
    ([(header::CONTENT_TYPE, "application/json")], body)
}

/// Build the router. `/events/all` is served by the `{channel}` handler (channel "all").
pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/audit/dead-events", get(dead_events))
        .route("/events/{channel}", get(sse_channel))
        .layer(CorsLayer::permissive())
        .with_state(state)
}

/// Poller thread: tail the event store, broadcast new events, track degraded state (L8).
pub fn spawn_poller(state: AppState, poll_ms: u64) {
    std::thread::spawn(move || {
        let mut hw: i64 = 0;
        loop {
            match open_db(&state.db_path) {
                Ok(conn) => loop {
                    match poll_once(&conn, hw, &state.tx) {
                        Ok(new_hw) => {
                            hw = new_hw;
                            state.high_water.store(hw, Relaxed);
                            state.db_connected.store(true, Relaxed);
                        }
                        Err(_) => {
                            state.db_connected.store(false, Relaxed);
                            break; // reopen on next outer iteration
                        }
                    }
                    std::thread::sleep(Duration::from_millis(poll_ms));
                },
                Err(_) => {
                    // Degraded: DB absent/unavailable. Keep the server up and retry.
                    state.db_connected.store(false, Relaxed);
                    std::thread::sleep(Duration::from_millis(poll_ms));
                }
            }
        }
    });
}
