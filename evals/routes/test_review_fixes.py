"""Fixes from the full product review (docs: decision 046, 047), against the live stack (make up).

Each test is a request the review reproduced. The starts are public stand-ins (evals/routes/starts.json).
"""

from functools import cache

import pytest

from api.constraints import RunConstraints
from api.engine import Engine, Start
from evals.routes.live import load_starts, stack_problem

OWNER = "owner-install-0001"
GUEST = "tester-install-0002"


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


# --- 1. the Apple Health prior is the owner's only ---------------------------------------------------------------


@cache
def williamsburg_flat(install: str | None):
    """The review's request: 8 flat miles from Williamsburg, built for one install."""
    s = load_starts()["williamsburg"]
    rc = RunConstraints(use_my_location=True, distance_mi=8.0, hills="avoid")
    eng = Engine(prior_installs=frozenset({OWNER})).for_install(install)
    return eng.build(rc, Start(s["lat"], s["lon"], "Williamsburg"), lambda e: None, f"r_prior_{install}")


def test_another_install_gets_no_route_you_run():
    for install in (GUEST, None):
        final = williamsburg_flat(install)
        assert final["routes"]
        assert not [r["label"] for r in final["routes"] if "route you run" in r["label"]], install


def test_the_owners_install_still_gets_the_prior():
    labels = [r["label"] for r in williamsburg_flat(OWNER)["routes"]]
    assert any("route you run" in label for label in labels), labels
