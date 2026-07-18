//! B0.6 sidecar tests: DB open + degraded (L8), schema-compat (L7), poll->broadcast,
//! per-channel filtering, dead-event audit (L10), and an HTTP /health smoke test.

use std::sync::atomic::{AtomicBool, AtomicI64};
use std::sync::Arc;

use rusqlite::Connection;
use sidecar::*;
use tokio::sync::broadcast;

fn schema_path() -> String {
    format!(
        "{}/../schema/migrations/0001_initial.sql",
        env!("CARGO_MANIFEST_DIR")
    )
}

fn temp_db(tag: &str) -> std::path::PathBuf {
    let mut p = std::env::temp_dir();
    p.push(format!("devh_sidecar_{}_{}.db", std::process::id(), tag));
    let _ = std::fs::remove_file(&p);
    p
}

fn writable_db_with_schema(tag: &str) -> (std::path::PathBuf, Connection) {
    let path = temp_db(tag);
    let conn = Connection::open(&path).unwrap();
    let sql = std::fs::read_to_string(schema_path()).unwrap();
    conn.execute_batch(&sql).unwrap();
    (path, conn)
}

fn insert_event(conn: &Connection, event_type: &str, payload: &str) {
    conn.execute(
        "INSERT INTO events (event_id, correlation_id, event_type, payload, prev_hash, hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        rusqlite::params![
            format!("id-{event_type}"),
            "corr-1",
            event_type,
            payload,
            "",
            format!("h-{event_type}")
        ],
    )
    .unwrap();
}

#[test]
fn open_db_ok_and_degraded() {
    let (path, _w) = writable_db_with_schema("open");
    assert!(open_db(path.to_str().unwrap()).is_ok());
    // L8: a missing DB opens as an error (degraded), it does not create/crash.
    assert!(open_db("/no/such/devharness_nope.db").is_err());
}

#[test]
fn events_schema_compat_l7() {
    let (_path, w) = writable_db_with_schema("schema");
    assert!(events_schema_ok(&w).unwrap());
    let empty = Connection::open_in_memory().unwrap();
    assert!(!events_schema_ok(&empty).unwrap());
}

#[test]
fn poll_emits_inserted_events() {
    let (path, w) = writable_db_with_schema("poll");
    insert_event(&w, "gate_fired", r#"{"gate":"g"}"#);
    insert_event(&w, "role_transitioned", r#"{"to_role":"director"}"#);

    let reader = open_db(path.to_str().unwrap()).unwrap();
    let (tx, mut rx) = broadcast::channel(16);
    let hw = poll_once(&reader, 0, &tx).unwrap();
    assert_eq!(hw, 2);

    let a = rx.try_recv().unwrap();
    let b = rx.try_recv().unwrap();
    assert_eq!(a.event_type, "gate_fired");
    assert_eq!(b.event_type, "role_transitioned");
    assert!(a.to_json(false).contains("\"event_type\":\"gate_fired\""));
    assert!(a.to_json(false).contains("\"replayed\":false"));
    assert!(a.to_json(true).contains("\"replayed\":true"));
}

#[test]
fn per_channel_filtering() {
    assert!(channel_matches("all", "gate_fired"));
    assert!(channel_matches("gate_fired", "gate_fired"));
    assert!(!channel_matches("gate_fired", "role_transitioned"));

    let msgs = vec![
        EventMsg { seq: 1, event_type: "gate_fired".into(), payload: "{}".into() },
        EventMsg { seq: 2, event_type: "role_transitioned".into(), payload: "{}".into() },
        EventMsg { seq: 3, event_type: "gate_fired".into(), payload: "{}".into() },
    ];
    let only = filtered_messages(msgs.clone(), "gate_fired");
    assert_eq!(only.len(), 2);
    assert!(only.iter().all(|m| m.event_type == "gate_fired"));
    assert_eq!(filtered_messages(msgs, "all").len(), 3);
}

#[test]
fn backlog_replays_history_with_global_max_seq() {
    // A fresh SSE client must replay PAST events (channel-filtered) — without this the dashboard
    // shows nothing until a new event fires. The replay reports the GLOBAL max seq, so the live
    // stream skips exactly what was replayed; using the per-channel max would re-send live events.
    let (path, w) = writable_db_with_schema("backlog");
    insert_event(&w, "gate_fired", r#"{"gate":"g"}"#);
    insert_event(&w, "role_transitioned", r#"{"to_role":"director"}"#);
    insert_event(&w, "role_transitioned", r#"{"to_role":"developer"}"#);
    let reader = open_db(path.to_str().unwrap()).unwrap();

    let (all, max_all) = backlog(&reader, "all").unwrap();
    assert_eq!(all.len(), 3);
    assert_eq!(max_all, 3);

    let (gates, max_gates) = backlog(&reader, "gate_fired").unwrap();
    assert_eq!(gates.len(), 1, "only the one gate_fired event is replayed for its channel");
    assert_eq!(gates[0].event_type, "gate_fired");
    assert_eq!(max_gates, 3, "max seq is GLOBAL (3), not the per-channel max (1)");
}

#[test]
fn dead_event_audit_l10() {
    let (_path, w) = writable_db_with_schema("dead");
    insert_event(&w, "gate_fired", "{}");
    let dead = dead_event_types(&w).unwrap();
    assert!(dead.contains(&"role_transitioned".to_string()));
    assert!(!dead.contains(&"gate_fired".to_string()));
    assert_eq!(dead.len(), EVENT_CATALOG.len() - 1); // derived: all catalog types minus the 1 that fired
}

#[tokio::test]
async fn server_starts_and_health_reports_connected() {
    let (path, _w) = writable_db_with_schema("health");
    let (tx, _) = broadcast::channel(16);
    let state = AppState {
        tx,
        db_path: path.to_str().unwrap().to_string(),
        high_water: Arc::new(AtomicI64::new(0)),
        db_connected: Arc::new(AtomicBool::new(false)),
    };
    spawn_poller(state.clone(), 20);

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app(state)).await.unwrap() });
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;

    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut s = tokio::net::TcpStream::connect(addr).await.unwrap();
    s.write_all(
        format!("GET /health HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\n\r\n").as_bytes(),
    )
    .await
    .unwrap();
    let mut buf = Vec::new();
    s.read_to_end(&mut buf).await.unwrap();
    let resp = String::from_utf8_lossy(&buf);
    assert!(resp.contains("200"), "no 200 in: {resp}");
    assert!(resp.contains("\"db_connected\":true"), "not connected in: {resp}");
    // CORS so the browser dashboard (different origin) can connect.
    assert!(
        resp.to_lowercase().contains("access-control-allow-origin"),
        "no CORS header in: {resp}"
    );
}

// M6: drive the /events/{channel} SSE route to a *subscribed client* and assert an event streams
// through. The poll->broadcast path is covered by poll_emits_inserted_events + per_channel_filtering;
// this is the previously-untested HTTP SSE delivery to a connected browser-like client.
#[tokio::test]
async fn sse_route_streams_event_to_subscribed_client_m6() {
    let (path, _w) = writable_db_with_schema("sse_route");
    let (tx, _) = broadcast::channel(16);
    let state = AppState {
        tx: tx.clone(),
        db_path: path.to_str().unwrap().to_string(),
        high_water: Arc::new(AtomicI64::new(0)),
        db_connected: Arc::new(AtomicBool::new(false)),
    };
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app(state)).await.unwrap() });
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;

    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut s = tokio::net::TcpStream::connect(addr).await.unwrap();
    s.write_all(
        format!("GET /events/all HTTP/1.1\r\nHost: {addr}\r\nConnection: keep-alive\r\n\r\n").as_bytes(),
    )
    .await
    .unwrap();

    // let the handler subscribe to the broadcast, then emit an event (as the poller would)
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    tx.send(EventMsg {
        seq: 1,
        event_type: "task_completed".to_string(),
        payload: "{\"ok\":true}".to_string(),
    })
    .unwrap();

    // read the SSE stream until the event arrives as a data frame (or time out)
    let mut acc = String::new();
    let got = tokio::time::timeout(std::time::Duration::from_secs(3), async {
        let mut buf = [0u8; 2048];
        loop {
            let n = s.read(&mut buf).await.unwrap();
            if n == 0 {
                break;
            }
            acc.push_str(&String::from_utf8_lossy(&buf[..n]));
            if acc.contains("task_completed") {
                break;
            }
        }
    })
    .await;
    assert!(got.is_ok(), "SSE stream timed out; got: {acc}");
    assert!(acc.contains("text/event-stream"), "not an SSE response: {acc}");
    assert!(acc.contains("task_completed"), "event not streamed to the subscribed client: {acc}");
}
