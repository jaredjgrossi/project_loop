"""Context scoring in worker processes (decision 018).

Scoring a candidate's context is mostly pure-Python geometry. On the generator's worker threads it held the
interpreter lock: a score that takes 0.15 s alone took 0.44 s in the pool, and GraphHopper requests that take 0.05 s
alone took 0.16 s, waiting for the lock to read their responses. Here a thread hands the route to a worker process and
waits without holding the lock. The code that scores is the same `score_context`, so results can't change.

LOOP_CONTEXT_PROCESSES sets the number of processes (default CONTEXT_PROCESSES); 0 scores on the calling thread. Each
process keeps one autocommit Postgres connection, so a score doesn't pay for a new connection and holds no transaction
open between scores.
"""

import os
import threading
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

CONTEXT_PROCESSES = 5  # decision 018: 5 processes with 6 generator threads was the best of the configurations tried
_pool: ProcessPoolExecutor | None = None
_lock = threading.Lock()
_conn = None  # one per worker process


def processes() -> int:
    return int(os.environ.get("LOOP_CONTEXT_PROCESSES", CONTEXT_PROCESSES))


def _connection():
    global _conn
    if _conn is None or _conn.closed:
        import psycopg

        from etl.load import database_url

        _conn = psycopg.connect(database_url(), autocommit=True)
    return _conn


def _score(coords, use_prior, lights, grid, start):
    from api.route_context import score_context

    return score_context(_connection(), coords, use_prior=use_prior, lights=lights, grid=grid, start=start)


def _ready(_=None) -> int:
    _connection()
    return os.getpid()


def pool() -> ProcessPoolExecutor | None:
    global _pool
    with _lock:
        if _pool is None and processes() > 0:
            _pool = ProcessPoolExecutor(processes(), mp_context=get_context("spawn"))
        return _pool


def warm() -> int:
    """Start the processes and open their connections ahead of the first request; returns how many answered."""
    p = pool()
    return 0 if p is None else len(set(p.map(_ready, range(processes() * 2))))


def score(coords, use_prior: bool, lights, grid, start):
    """score_context for this route, in a worker process (or on this thread when processes() is 0)."""
    p = pool()
    if p is None:
        return _score(coords, use_prior, lights, grid, start)
    return p.submit(_score, coords, use_prior, lights, grid, start).result()
