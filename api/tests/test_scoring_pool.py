import os

import api.scoring_pool as sp


def test_scoring_runs_in_another_process_and_can_be_turned_off(monkeypatch):
    # The pool runs the same score_context; here _score is swapped for a stand-in that needs no database.
    monkeypatch.setenv("LOOP_CONTEXT_PROCESSES", "0")
    monkeypatch.setattr(sp, "_pool", None)
    monkeypatch.setattr(sp, "_score", lambda *a: ("inline", os.getpid()))
    assert sp.pool() is None and sp.score([[0, 0]], True, None, None, None) == ("inline", os.getpid())


def test_a_worker_process_answers_from_its_own_pid(monkeypatch):
    monkeypatch.setenv("LOOP_CONTEXT_PROCESSES", "1")
    monkeypatch.setattr(sp, "_pool", None)
    p = sp.pool()
    try:
        assert p.submit(os.getpid).result() != os.getpid()
    finally:
        p.shutdown()
        sp._pool = None
