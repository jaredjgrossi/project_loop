"""Today's top 3 at every review row and lights setting, pinned (decision 018), so speed work can't silently change
results. Needs the live stack:  uv run pytest evals/

When a change is meant to change results, re-pin with `uv run python -m evals.routes.time_generation --pin
evals/routes/pinned_top3.json` and say in the decision record which rows changed and why.
"""

import json
from pathlib import Path

import pytest

from evals.routes.live import stack_problem, top_loops
from evals.routes.time_generation import summary

PINNED = json.loads((Path(__file__).resolve().parent / "pinned_top3.json").read_text())["rows"]
CASES = sorted(PINNED)


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


def describe(rows: list[dict]) -> str:
    return "; ".join(f"#{i} {r['label']} ({r['kind']}, {r['distance_m']} m, score {r['score']}, {r['fingerprint']})"
                     for i, r in enumerate(rows, 1))


@pytest.mark.parametrize("case", CASES)
def test_top3_is_unchanged(case):
    start_id, miles, lights = case.split("|")
    got = [summary(c) for c in top_loops(start_id, float(miles), 3, prefs=(("lights", lights),))]
    key = lambda rows: [(r["label"], r["kind"], r["fingerprint"]) for r in rows]
    assert key(got) == key(PINNED[case]), f"\n  pinned: {describe(PINNED[case])}\n  now:    {describe(got)}"
