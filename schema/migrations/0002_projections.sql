-- 0002_projections.sql — B0.4 projection tables (spec §Data model, rev 0.3.2).
-- The 12 dashboard tile backing tables. Derived read models, rebuildable from the
-- event log (Invariant 8). event_seq = events.seq of the event that last wrote the row.

CREATE TABLE proj_role_state (         -- tile 1: active role & FSM state
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    role      TEXT NOT NULL,
    event_seq INTEGER NOT NULL
);

CREATE TABLE proj_spec (               -- tile 2: current spec + sign-off
    spec_id   TEXT PRIMARY KEY,
    title     TEXT,
    signed    INTEGER NOT NULL DEFAULT 0,
    signed_at TIMESTAMP,
    event_seq INTEGER NOT NULL
);

CREATE TABLE proj_plan (               -- tile 3: current plan / task list
    task_id   TEXT PRIMARY KEY,
    ordinal   INTEGER NOT NULL,
    summary   TEXT,
    status    TEXT,
    event_seq INTEGER NOT NULL
);

CREATE TABLE proj_task_queue (         -- tile 4: task queue
    task_id    TEXT PRIMARY KEY,
    task_class TEXT,
    state      TEXT NOT NULL,
    event_seq  INTEGER NOT NULL
);

CREATE TABLE proj_review (             -- tile 5: diff under review
    task_id   TEXT PRIMARY KEY,
    diff_ref  TEXT,
    reviewer  TEXT,
    state     TEXT,
    event_seq INTEGER NOT NULL
);

CREATE TABLE proj_gate_fires (         -- tile 6: gate fires
    event_seq      INTEGER PRIMARY KEY,
    gate           TEXT NOT NULL,
    decision       TEXT NOT NULL,
    reason         TEXT,
    purpose        TEXT,
    fix            TEXT,
    correlation_id TEXT
);

CREATE TABLE proj_cost (               -- tile 7: per-role cost vs budget
    role       TEXT PRIMARY KEY,
    spent_usd  REAL NOT NULL DEFAULT 0,
    budget_usd REAL,
    event_seq  INTEGER NOT NULL
);

CREATE TABLE proj_terminal_outcomes (  -- tile 8: terminal outcomes
    task_id   TEXT PRIMARY KEY,
    outcome   TEXT NOT NULL,
    detail    TEXT,
    event_seq INTEGER NOT NULL
);

CREATE TABLE proj_antibody_queue (     -- tile 9: antibody candidates
    candidate_id TEXT PRIMARY KEY,
    summary      TEXT,
    status       TEXT NOT NULL,
    event_seq    INTEGER NOT NULL
);

CREATE TABLE proj_gate_change_queue (  -- tile 10: gate-change candidates
    candidate_id TEXT PRIMARY KEY,
    gate         TEXT,
    proposal     TEXT,
    status       TEXT NOT NULL,
    event_seq    INTEGER NOT NULL
);

CREATE TABLE proj_lock (               -- tile 11: single-writer lock holder
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    holder      TEXT,
    task_id     TEXT,
    acquired_at TIMESTAMP,
    event_seq   INTEGER NOT NULL
);

CREATE TABLE proj_boot_parity (        -- tile 12: boot-check / parity status
    check_name TEXT PRIMARY KEY,
    commitment TEXT NOT NULL,
    status     TEXT NOT NULL,
    event_seq  INTEGER
);
