"""Every route a reviewer rejected, as a failing eval (decision 009).

Each case in rejected_routes.json stays red until the generator stops producing the rejected route. Runs against
the live stack:  uv run pytest evals/
"""

import pytest

from evals.routes.live import closest_approach_m, load_rejected, stack_problem, top_loops

CASES = [(case, miles) for case in load_rejected() for miles in case["miles"]]


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


@pytest.mark.parametrize(("case", "miles"), CASES, ids=[f"{c['id']}-{m:g}mi" for c, m in CASES])
def test_rejected_route_is_not_produced(case, miles):
    rule = case["rule"]
    assert rule["type"] == "avoid_area", f"unknown rule type {rule['type']!r}"
    candidates = top_loops(case["start"], miles, case["top"])
    assert candidates, f"no loop generated from {case['start']} at {miles:g} mi"
    offenders = [
        f"rank {rank} ({c.label}, shape score {c.score:.0f})"
        for rank, c in enumerate(candidates, start=1)
        if closest_approach_m(c.route.coordinates, rule["area"]) == 0
    ]
    assert not offenders, f"{case['reason']} Still produced, through {rule['name']}: {', '.join(offenders)}"
