# 039: Scoring-pool workers end with their parent

**Status:** accepted (2026-11-09). Asked for by Jared before merging PR #11. Amends decision 018 (context scoring
in worker processes).

## What happened
- Decision 018's pool is one set of spawn processes per Python process (5 by default). It starts on first use, and
  every build reuses it, so builds never added workers.
- When the process that started the pool was killed outright, its workers kept running for good, each with an
  open Postgres connection. Their new parent was launchd, and they were idle at 0% CPU.
  - "Outright" means a `kill` of the parent alone, a test timeout that ends with `os._exit`, or a hung eval stopped
    by hand.
  - On 2026-11-09 there were nine such sets, holding 43 idle connections out of Postgres's 100.
- A normal exit was fine: `concurrent.futures` shuts the pool down at exit. Closing the server's terminal tab was
  fine too, because the hangup reaches the whole process group.

## Decision
- **Each worker watches its parent** (`api/scoring_pool.py`):
  - an initializer starts a daemon thread that checks `os.getppid()` every second;
  - once the worker has been re-parented, it exits;
  - the pool's resource tracker then sees its pipe close and exits too.
- **The server stops the pool on shutdown.** A restart starts one new set.
- **`scoring_pool.shutdown()`** for tests and the server.

## Tests (`api/tests/test_scoring_pool.py`)
- **20 builds:** the worker count stays at 2 (with `LOOP_CONTEXT_PROCESSES=2`). Every candidate's score goes
  through the pool, as a real score does.
- **Shutdown:** stops the workers, and the next use starts exactly one new set.
- **A parent killed with SIGKILL:** no atexit and no shutdown, yet both workers are gone within seconds. With the
  watchdog turned off, this test fails.
