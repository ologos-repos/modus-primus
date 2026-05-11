-- means/agents/data/agents.sqlite — schema applied on store init.
--
-- runs: one row per spawned agent run. Status transitions
--   pending → running → done | error | cancelled
--
-- events: per-run event log. Mirrors console.turns.TurnEvent shape so the
-- /runs/{id}/stream SSE endpoint can re-emit rows verbatim.
--
-- Phase 2 extends events.type with 'tool_call' / 'tool_result'; phase 3
-- adds 'qa_step'; phase 4 introduces an approvals table.

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    agent_name          TEXT NOT NULL,
    spec_hash           TEXT NOT NULL,
    fork                TEXT NOT NULL,
    status              TEXT NOT NULL,
    started_at          REAL NOT NULL,
    completed_at        REAL,
    exit_code           INTEGER,
    prompt              TEXT NOT NULL,
    cost_usd            REAL DEFAULT 0,
    parent_session_id   TEXT,
    parent_turn_id      TEXT,
    pid                 INTEGER,
    error               TEXT,
    -- Phase 3: QA pass outcome. null = QA skipped (no spec.qa.criteria).
    -- Otherwise one of: pass | fail | error.
    qa_outcome          TEXT,
    qa_reason           TEXT
);

CREATE INDEX IF NOT EXISTS runs_agent_started
    ON runs (agent_name, started_at DESC);

CREATE INDEX IF NOT EXISTS runs_status
    ON runs (status);

CREATE TABLE IF NOT EXISTS events (
    run_id              TEXT NOT NULL,
    seq                 INTEGER NOT NULL,
    ts                  REAL NOT NULL,
    type                TEXT NOT NULL,
    data                TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- Phase 8: workflow_runs — one row per linear-chain execution. Each step
-- of the chain creates a normal `runs` row linked back via the new
-- `parent_workflow_run_id` column (added by idempotent ALTER in store.py).
CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_run_id     TEXT PRIMARY KEY,
    workflow_name       TEXT NOT NULL,
    spec_hash           TEXT NOT NULL,
    status              TEXT NOT NULL,         -- pending | running | done | error | cancelled
    started_at          REAL NOT NULL,
    completed_at        REAL,
    prompt              TEXT NOT NULL,         -- initial {input}
    final_output        TEXT,                  -- last step's text output on success
    error               TEXT,
    pid                 INTEGER
);

CREATE INDEX IF NOT EXISTS workflow_runs_started
    ON workflow_runs (started_at DESC);

-- Phase 9: per-trigger state. Persisted across restarts so a missed
-- fire window is recoverable (catch-up policy: at-most-one fire on
-- restart). The trigger spec itself lives in the filesystem (markdown
-- frontmatter under specs/triggers/); this table only stores runtime
-- state.
CREATE TABLE IF NOT EXISTS trigger_state (
    name             TEXT PRIMARY KEY,
    last_fired_at    REAL,
    fire_count       INTEGER NOT NULL DEFAULT 0
);
