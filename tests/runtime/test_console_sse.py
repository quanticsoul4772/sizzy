"""Live SSE-stream consumer for the operator console.

The console keeps its surfaced loop state in sync by consuming the SAME event
surface the dashboard consumes — the sidecar's ``/events/{channel}`` SSE feed —
not a parallel telemetry layer. These tests pin the sidecar wire format
(``EventMsg::to_json``), the SSE parse rules, the read-only HTTP-GET posture,
and that following the stream re-derives the displayed loop state from the
projections (Invariant 8 keeps them in step with the event log the sidecar
tails).
"""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import (
    ConsoleApp,
    SSEFrame,
    StreamConsumer,
    parse_sse_frames,
    stream_url,
)
from devharness.console.sse import iter_text_lines, sidecar_base


# --- sidecar URL resolution: the same feed the dashboard uses -----------------


def test_default_sidecar_base_is_the_dashboard_default(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_SIDECAR_ADDR", raising=False)
    assert sidecar_base() == "http://127.0.0.1:8080"


def test_sidecar_base_normalises_bare_host_port(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_SIDECAR_ADDR", "127.0.0.1:9999")
    assert sidecar_base() == "http://127.0.0.1:9999"


def test_sidecar_base_honours_scheme_and_explicit_arg(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_SIDECAR_ADDR", "https://host:8443/")
    assert sidecar_base() == "https://host:8443"
    assert sidecar_base("http://other:1234") == "http://other:1234"


def test_stream_url_targets_the_shared_all_channel():
    # "all" is the single shared feed the dashboard's EventSource subscribes to —
    # consuming it (not a private channel) is what "no parallel telemetry" means.
    assert stream_url("all", "http://127.0.0.1:8080") == "http://127.0.0.1:8080/events/all"


# --- SSE wire-format parsing --------------------------------------------------


def _sidecar_frame(seq, event_type, payload_json, replayed=False):
    """An SSE block exactly as the sidecar emits it (EventMsg::to_json)."""
    data = (
        f'{{"seq":{seq},"event_type":"{event_type}",'
        f'"replayed":{str(replayed).lower()},"payload":{payload_json}}}'
    )
    return f"event: {event_type}\ndata: {data}\n\n"


def test_parses_a_single_sidecar_frame():
    text = _sidecar_frame(1, "role_transitioned", '{"to_role":"director"}')
    frames = list(parse_sse_frames(text.splitlines(keepends=True)))
    assert len(frames) == 1
    f = frames[0]
    assert isinstance(f, SSEFrame)
    assert f.seq == 1
    assert f.event_type == "role_transitioned"
    assert f.replayed is False
    assert f.payload == {"to_role": "director"}


def test_distinguishes_replayed_backlog_from_live():
    backlog = _sidecar_frame(1, "spec_signed", "{}", replayed=True)
    live = _sidecar_frame(2, "task_started", "{}", replayed=False)
    frames = list(parse_sse_frames((backlog + live).splitlines(keepends=True)))
    assert [f.seq for f in frames] == [1, 2]
    assert frames[0].replayed is True
    assert frames[1].replayed is False


def test_ignores_keepalive_comment_lines():
    text = ":\n:keep-alive\n" + _sidecar_frame(5, "role_transitioned", "{}")
    frames = list(parse_sse_frames(text.splitlines(keepends=True)))
    assert [f.seq for f in frames] == [5]


def test_rejoins_multiline_data():
    block = 'event: x\ndata: {"seq":3,"event_type":"x",\ndata: "replayed":false,"payload":7}\n\n'
    frames = list(parse_sse_frames(block.splitlines(keepends=True)))
    assert len(frames) == 1
    assert frames[0].seq == 3
    assert frames[0].payload == 7


def test_strips_only_one_leading_space_after_colon():
    # SSE strips a single space after "data:"; a second space is part of the value.
    block = 'data:  {"seq":9,"event_type":"y","replayed":false,"payload":null}\n\n'
    # leading-space-preserved JSON " {...}" still parses (json.loads tolerates it)
    frames = list(parse_sse_frames(block.splitlines(keepends=True)))
    assert frames and frames[0].seq == 9


def test_drops_malformed_and_incomplete_blocks():
    good = _sidecar_frame(1, "ok", "{}")
    bad_json = "event: y\ndata: {not json}\n\n"
    no_seq = 'event: z\ndata: {"event_type":"z","replayed":false}\n\n'
    trailing = "event: late\ndata: {\"seq\":2}"  # no terminating blank line
    text = good + bad_json + no_seq + trailing
    frames = list(parse_sse_frames(text.splitlines(keepends=True)))
    assert [f.seq for f in frames] == [1]


def test_iter_text_lines_decodes_bytes():
    stream = io.BytesIO(b"event: a\ndata: {}\n")
    assert list(iter_text_lines(stream)) == ["event: a\n", "data: {}\n"]


# --- StreamConsumer: read-only HTTP GET against the sidecar -------------------


class _FakeResponse(io.BytesIO):
    """A byte stream standing in for the sidecar's HTTP SSE response."""


def _fake_opener(captured):
    def opener(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(captured["body"])

    return opener


def test_consumer_opens_the_all_channel_and_yields_frames():
    captured = {"body": (
        _sidecar_frame(1, "role_transitioned", '{"to_role":"director"}')
        + _sidecar_frame(2, "spec_signed", "{}")
    ).encode("utf-8")}
    consumer = StreamConsumer(addr="http://127.0.0.1:8080", opener=_fake_opener(captured))
    frames = list(consumer.frames())
    # consumes the same shared feed the dashboard does — no private/parallel channel
    assert captured["url"] == "http://127.0.0.1:8080/events/all"
    assert [f.seq for f in frames] == [1, 2]
    assert [f.event_type for f in frames] == ["role_transitioned", "spec_signed"]


def test_consumer_passes_timeout_when_set():
    captured = {"body": b""}
    StreamConsumer(opener=_fake_opener(captured), timeout=2.5)
    consumer = StreamConsumer(opener=_fake_opener(captured), timeout=2.5)
    list(consumer.frames())
    assert captured["kwargs"].get("timeout") == 2.5


# --- Integration: the console stays in sync with the projection surface --------


def _app():
    return ConsoleApp(db_path=":memory:").connect()


def test_follow_keeps_surfaced_state_in_sync_with_projections():
    app = _app()
    bus = app.writer  # writes only ever go through EventBus.emit_sync

    bus.emit_sync("role_transitioned", {"to_role": "director"}, "c1")
    bus.emit_sync(
        "spec_signed",
        {"spec_id": "spec-7", "signer": "operator", "signed_at_millis": 100},
        "c1",
    )

    # The sidecar would broadcast these two events; feed the matching frames.
    body = (
        _sidecar_frame(1, "role_transitioned", '{"to_role":"director"}')
        + _sidecar_frame(2, "spec_signed", '{"spec_id":"spec-7"}')
    ).encode("utf-8")
    captured = {"body": body}
    consumer = StreamConsumer(opener=_fake_opener(captured))

    seen = []
    final = app.follow(consumer=consumer, on_frame=lambda f, s: seen.append((f.seq, s)))

    # state surfaced after following equals what the projection surface holds —
    # the same surface the dashboard renders from (no parallel telemetry).
    assert final == app.loop_state()
    assert final.active_role == "director"
    assert final.spec_signed is True
    assert final.signed_spec_id == "spec-7"
    assert app.synced_state() == final
    assert app.live_seq == 2
    assert app.last_frame is not None and app.last_frame.seq == 2
    assert [seq for seq, _ in seen] == [1, 2]


def test_follow_respects_max_frames_bound():
    app = _app()
    body = b"".join(
        _sidecar_frame(i, "role_transitioned", "{}").encode("utf-8") for i in range(1, 6)
    )
    consumer = StreamConsumer(opener=_fake_opener({"body": body}))
    count = {"n": 0}

    def _bump(_f, _s):
        count["n"] += 1

    app.follow(consumer=consumer, on_frame=_bump, max_frames=2)
    assert count["n"] == 2
    assert app.live_seq == 2


def test_follow_does_not_write_the_event_store():
    app = _app()
    app.writer.emit_sync("role_transitioned", {"to_role": "research"}, "c1")
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    body = _sidecar_frame(1, "role_transitioned", "{}").encode("utf-8")
    consumer = StreamConsumer(opener=_fake_opener({"body": body}))
    app.follow(consumer=consumer)

    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after == before  # consuming the stream is read-only


def test_follow_with_no_frames_returns_current_state():
    app = _app()
    consumer = StreamConsumer(opener=_fake_opener({"body": b""}))
    state = app.follow(consumer=consumer)
    assert state == app.loop_state()
    assert app.last_frame is None
