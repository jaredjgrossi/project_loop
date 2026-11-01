"""Positive check from the reviewer's real runs (decision 011): in a neighborhood the runner actually runs from, the
best generated route should not score worse than their typical real run there.

Both sides are trimmed 200 m at both ends and scored by the same ranking (api/ranking.py) with the same measured
context (api/route_context.py) and neutral preferences, with "matches routes you run" off. Generated routes are made
without the reviewer's runs (no corridor placement from them), so the runs are only the answer key. A real run is ranked as an out-and-back when most of its
second half revisits the first, else as a loop. Needs the live stack and the reviewer's personal data
(data/health/matched.jsonl from evals/health_routes/match_runs.py, and the runner_prior table from build_prior.py);
skips without them, so it only runs on the reviewer's machine.
"""

import json
import math
import statistics as st
from pathlib import Path

import psycopg
import pytest

from api.constraints import DEFAULTS
from api.ranking import rank
from api.route_context import score_context
from api.shape import shape_metrics, trim_ends
from etl.load import database_url
from evals.routes.live import load_starts, stack_problem, top_loops

MATCHED = Path(__file__).resolve().parents[2] / "data" / "health" / "matched.jsonl"
TYPICAL_MILES = 3.0  # the reviewer's median run over the last 12 months
NEAR_START_M = 1500
MIN_RUNS = 20  # only judge starts the runner has run from often enough for a "typical" run to mean something
TRIM_M = 200.0


def _m(a, b) -> float:
    return math.hypot((a[0] - b[0]) * 111_320 * math.cos(math.radians(40.75)), (a[1] - b[1]) * 110_574)


def _score(conn, trimmed, kind=None) -> float:
    # "Matches routes you run" is off on both sides: real runs would score themselves ~100% on it.
    shape = shape_metrics(trimmed)
    kind = kind or ("out_and_back" if shape.out_and_back_pct >= 50 else "loop")
    return rank(kind, shape, DEFAULTS, score_context(conn, trimmed, use_prior=False)).score


def _runs():
    return [json.loads(line) for line in MATCHED.open()] if MATCHED.exists() else []


def _home_starts():
    runs = _runs()
    starts = load_starts()
    out = []
    for sid, s in starts.items():
        near = [r for r in runs if _m(r["coordinates"][0], (s["lon"], s["lat"])) <= NEAR_START_M]
        if len(near) >= MIN_RUNS:
            out.append((sid, near))
    return out


HOME = _home_starts()


@pytest.fixture(scope="module", autouse=True)
def live_stack_and_personal_data():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)
    if not MATCHED.exists():
        pytest.skip("No personal run data (data/health/matched.jsonl); this eval runs on the reviewer's machine only")
    with psycopg.connect(database_url()) as conn:
        if not conn.execute("SELECT to_regclass('runner_prior') IS NOT NULL").fetchone()[0]:
            pytest.skip("runner_prior not built; run python -m evals.health_routes.build_prior")


@pytest.mark.parametrize(("start_id", "runs"), HOME, ids=[sid for sid, _ in HOME])
def test_best_generated_route_is_not_worse_than_a_typical_real_run(start_id, runs):
    with psycopg.connect(database_url()) as conn:
        real = st.median(_score(conn, r["coordinates"]) for r in runs)
        # Generated without the reviewer's runs: they are the answer key here, never an input (decision 012).
        candidates = top_loops(start_id, TYPICAL_MILES, 3, use_prior=False)
        assert candidates, f"no route generated from {start_id}"
        generated = [(_score(conn, trim_ends(c.route.coordinates, TRIM_M), c.kind), c.label) for c in candidates]
    best, label = max(generated)
    assert best >= real, (
        f"From {start_id} at {TYPICAL_MILES:g} mi the best generated route ({label}) scores {best:.0f}, "
        f"below the reviewer's typical real run there ({real:.0f}, median of {len(runs)} runs)."
    )
