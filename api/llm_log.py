"""Log every Claude call into llm_calls (CLAUDE.md; decision 025).

What is kept: the raw request text, the model and effort, tokens (input, output, cache reads and writes), cost,
latency, stop reason and request id. Never the runner's location or any coordinates. The table is private: it lives
only in the local Postgres, is never exported or committed, and rows older than RETENTION_DAYS are deleted on every
write (rule R8: raw text can hold health details, kept here only for those 30 days).

Logging never breaks a parse: if Postgres can't be reached, the call is reported once on stderr and skipped.
"""

import sys
import threading

import psycopg

RETENTION_DAYS = 30

DDL = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id                  bigserial PRIMARY KEY,
    created_at          timestamptz NOT NULL DEFAULT now(),
    purpose             text NOT NULL,          -- 'parse'
    prompt_version      text NOT NULL,
    model               text NOT NULL,
    effort              text,
    thinking            text,
    request_text        text,                   -- the runner's raw words; private, 30 days
    input_tokens        integer,
    output_tokens       integer,
    cache_read_tokens   integer,
    cache_write_tokens  integer,
    cost_usd            numeric(12, 8),
    latency_ms          integer,
    stop_reason         text,
    request_id          text,
    error               text
);
CREATE INDEX IF NOT EXISTS llm_calls_created_at_idx ON llm_calls (created_at);
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS thinking text;  -- "adaptive" or "off" (added 2026-11-08)
"""

COLUMNS = ("purpose", "prompt_version", "model", "effort", "thinking", "request_text", "input_tokens", "output_tokens",
           "cache_read_tokens", "cache_write_tokens", "cost_usd", "latency_ms", "stop_reason", "request_id", "error")

_warned = False
_ready = False  # the DDL takes a table lock, so it runs once per process (parallel parses deadlocked, 2026-11-08)
_ddl_lock = threading.Lock()


def log_call(row: dict, conn=None) -> None:
    """Insert one call. `row` holds COLUMNS; anything else (such as a location) is refused."""
    global _warned, _ready
    extra = set(row) - set(COLUMNS)
    if extra:
        raise ValueError(f"llm_calls doesn't keep {sorted(extra)}")
    own = conn is None
    try:
        if own:
            from etl.load import database_url
            conn = psycopg.connect(database_url(), connect_timeout=2, autocommit=True)
        if not _ready:
            with _ddl_lock:
                if not _ready:
                    conn.execute(DDL)
                    _ready = True
        insert = f"INSERT INTO llm_calls ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))})"
        try:
            conn.execute(insert, [row.get(c) for c in COLUMNS])
        except psycopg.errors.DeadlockDetected:  # one retry: the other writer has finished by now
            conn.execute(insert, [row.get(c) for c in COLUMNS])
        conn.execute("DELETE FROM llm_calls WHERE created_at < now() - make_interval(days => %s)", (RETENTION_DAYS,))
    except psycopg.Error as exc:
        if not _warned:
            print(f"llm_calls: a call was not logged ({exc.__class__.__name__}: {exc})", file=sys.stderr)
            _warned = True
    finally:
        if own and conn is not None:
            conn.close()
