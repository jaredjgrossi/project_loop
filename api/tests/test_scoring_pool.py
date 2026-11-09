"""The scoring pool's processes (decision 018): one set per process, reused by every build, and gone when the
process that started them is (2026-11-09: killed parents left orphaned workers running for good)."""

import multiprocessing
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from api import scoring_pool


@pytest.fixture
def two_processes(monkeypatch):
    scoring_pool.shutdown()
    monkeypatch.setenv("LOOP_CONTEXT_PROCESSES", "2")
    yield
    scoring_pool.shutdown()


def workers() -> int:
    return len(multiprocessing.active_children())


def start_all() -> set[int]:
    """The pool starts workers as work arrives; work that waits a moment starts every one."""
    return set(scoring_pool.pool().map(scoring_pool._pid, [0.3] * (2 * scoring_pool.processes())))


def test_the_worker_count_stays_flat_after_20_builds(two_processes):
    from api.engine import Start
    from api.generate import generate_loops
    from api.tests.test_a_to_b import KIPS, area_route, straight_route
    from api.tests.test_engine import engine, rc

    def context_for(*a, **kw):  # every candidate goes through a pool process, as a real score does
        def score(coords):
            scoring_pool.pool().submit(os.getpid).result()
            return None
        return score

    e = engine(generate_loops, routers_fn=lambda zones, lights, closures: (straight_route, None, area_route),
               context_for_fn=context_for)
    e.build(rc(distance_mi=3.0), Start(*KIPS, "x"), lambda ev: None, "r_0")
    start_all()
    first = workers()
    assert first == 2
    for i in range(1, 21):
        final = e.build(rc(distance_mi=3.0), Start(*KIPS, "x"), lambda ev: None, f"r_{i}")
        assert final["routes"]
    assert workers() == first


def test_shutdown_stops_the_workers_and_a_new_build_starts_one_set(two_processes):
    start_all()
    assert workers() == 2
    scoring_pool.shutdown()
    assert workers() == 0
    start_all()
    assert workers() == 2


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_workers_exit_when_their_parent_is_killed():
    """A parent killed outright (SIGKILL: no atexit, no shutdown) leaves no workers behind."""
    script = textwrap.dedent("""
        import os, sys, time
        os.environ["LOOP_CONTEXT_PROCESSES"] = "2"
        from api import scoring_pool
        if __name__ == "__main__":
            pids = set(scoring_pool.pool().map(scoring_pool._pid, [0.3] * 4))
            print(*sorted(pids), flush=True)
            time.sleep(60)
    """)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, cwd=root,
                            env={**os.environ, "PYTHONPATH": root})
    try:
        pids = [int(x) for x in proc.stdout.readline().split()]  # the pool's two workers
        assert len(pids) == 2 and all(_alive(p) for p in pids)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        deadline = time.time() + 10
        while time.time() < deadline and any(_alive(p) for p in pids):
            time.sleep(0.2)
        assert not any(_alive(p) for p in pids), "workers outlived their parent"
    finally:
        if proc.poll() is None:
            proc.kill()


# ---- from decision 018 ----------------------------------------------------------------------------------------------

def test_scoring_runs_in_another_process_and_can_be_turned_off(monkeypatch):
    # The pool runs the same score_context; here _score is swapped for a stand-in that needs no database.
    monkeypatch.setenv("LOOP_CONTEXT_PROCESSES", "0")
    monkeypatch.setattr(scoring_pool, "_pool", None)
    monkeypatch.setattr(scoring_pool, "_score", lambda *a: ("inline", os.getpid()))
    assert scoring_pool.pool() is None
    assert scoring_pool.score([[0, 0]], True, None, None, None) == ("inline", os.getpid())


def test_a_worker_process_answers_from_its_own_pid(monkeypatch):
    monkeypatch.setenv("LOOP_CONTEXT_PROCESSES", "1")
    monkeypatch.setattr(scoring_pool, "_pool", None)
    p = scoring_pool.pool()
    try:
        assert p.submit(os.getpid).result() != os.getpid()
    finally:
        p.shutdown()
        scoring_pool._pool = None
