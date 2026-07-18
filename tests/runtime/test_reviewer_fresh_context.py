"""B2.5: reviewer fresh-context discipline + spawn_role fresh_context flag."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.roles.fresh_context import FreshContextRequired
from devharness.roles.reviewer import ReviewerRole


class _FakeParallax:
    async def verify(self, **p):
        ...

    async def check(self, **p):
        ...

    async def grounded_verify(self, **p):
        ...


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn, EventBus(conn)


def test_non_fresh_reviewer_spawn_raises():
    conn, bus = _setup()
    with pytest.raises(FreshContextRequired):
        ReviewerRole.spawn(conn=conn, correlation_id="c", parallax=_FakeParallax(), event_bus=bus, fresh_context=False)


def test_fresh_reviewer_spawn_sets_flag():
    conn, bus = _setup()
    reviewer = ReviewerRole.spawn(conn=conn, correlation_id="c", parallax=_FakeParallax(), event_bus=bus, fresh_context=True)
    assert reviewer.fresh_context is True
