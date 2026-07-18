"""Live SSE-stream consumer for the operator console.

The console keeps its surfaced loop state live by consuming the SAME event
surface the dashboard consumes — the sidecar's read-only ``/events/{channel}``
SSE endpoint (``sidecar/src/lib.rs``) — never a parallel telemetry channel. The
sidecar tails the single event log and broadcasts each frame as an SSE message
whose ``data`` body is the JSON the dashboard already parses
(``{"seq","event_type","replayed","payload"}`` — see ``EventMsg::to_json``).

This module parses that wire format and yields :class:`SSEFrame` objects. It is
read-only by construction: it issues HTTP GETs against the sidecar and never
writes the event store (the console's sole write path stays ``EventBus``).
"""

import io
import json
import os
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

# Matches the dashboard default (sidecar binds 127.0.0.1:8080). DEVHARNESS_SIDECAR_ADDR
# may be given with or without a scheme (the sidecar's bind form is host:port).
DEFAULT_SIDECAR_ADDR = "http://127.0.0.1:8080"


@dataclass(frozen=True)
class SSEFrame:
    """One parsed sidecar SSE frame — the same surface a dashboard tile sees.

    ``replayed`` is true for backlog events the sidecar sends on connect; live
    events carry it false. ``payload`` is the already-decoded event body.
    """

    seq: int
    event_type: str
    replayed: bool
    payload: Any


def sidecar_base(addr: str | None = None) -> str:
    """Resolve the sidecar base URL: explicit arg, then env, then the default.

    A bare ``host:port`` (the sidecar's bind form) is normalised to an
    ``http://`` URL so it can be used as an HTTP endpoint.
    """
    base = addr or os.environ.get("DEVHARNESS_SIDECAR_ADDR") or DEFAULT_SIDECAR_ADDR
    base = base.strip()
    if "://" not in base:
        base = "http://" + base
    return base.rstrip("/")


def stream_url(channel: str = "all", addr: str | None = None) -> str:
    """The sidecar SSE URL for a channel ("all" is the dashboard's shared feed)."""
    return f"{sidecar_base(addr)}/events/{channel}"


def iter_text_lines(byte_stream: Iterable[bytes]) -> Iterator[str]:
    """Decode a byte line-stream (the HTTP response) to UTF-8 text lines."""
    for raw in byte_stream:
        if isinstance(raw, bytes):
            yield raw.decode("utf-8", "replace")
        else:
            yield raw


def _frame_from_data(event_type: str | None, data: str) -> SSEFrame | None:
    """Build a frame from a dispatched SSE ``data`` body, or None if unusable."""
    try:
        obj = json.loads(data)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    seq = obj.get("seq")
    if not isinstance(seq, int):
        return None
    etype = obj.get("event_type") or event_type
    if not isinstance(etype, str):
        return None
    return SSEFrame(
        seq=seq,
        event_type=etype,
        replayed=bool(obj.get("replayed", False)),
        payload=obj.get("payload"),
    )


def parse_sse_frames(lines: Iterable[str]) -> Iterator[SSEFrame]:
    """Parse an SSE text-line stream into :class:`SSEFrame` objects.

    Implements the dispatch rules the wire needs: ``event:``/``data:`` fields,
    a single leading space after the colon stripped, multi-line ``data``
    re-joined with newlines, comment lines (``:`` keep-alives) ignored, and a
    frame dispatched on each blank line. A trailing block with no terminating
    blank line is not dispatched (it may be a partial read), matching SSE.
    """
    event_type: str | None = None
    data_parts: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        if line == "":
            if data_parts:
                frame = _frame_from_data(event_type, "\n".join(data_parts))
                if frame is not None:
                    yield frame
            event_type = None
            data_parts = []
            continue
        if line.startswith(":"):
            continue  # comment / keep-alive ping
        field, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value
        elif field == "data":
            data_parts.append(value)
        # id/retry/unknown fields are ignored


class StreamConsumer:
    """Opens the sidecar SSE stream and yields parsed frames.

    The ``opener`` seam (default :func:`urllib.request.urlopen`) lets a test feed
    a canned byte stream without a live sidecar; production uses the real HTTP
    GET. Read-only: it only ever issues GETs against the sidecar.
    """

    def __init__(
        self,
        channel: str = "all",
        addr: str | None = None,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout: float | None = None,
    ) -> None:
        self.channel = channel
        self.url = stream_url(channel, addr)
        self._opener = opener
        self._timeout = timeout

    def _open(self) -> Any:
        if self._timeout is not None:
            return self._opener(self.url, timeout=self._timeout)
        return self._opener(self.url)

    def frames(self) -> Iterator[SSEFrame]:
        """Open the stream and yield frames until the connection closes."""
        resp = self._open()
        with closing(resp):
            stream = resp if hasattr(resp, "__iter__") else io.BytesIO()
            yield from parse_sse_frames(iter_text_lines(stream))
