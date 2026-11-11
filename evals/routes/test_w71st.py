"""5 miles from W 71st St (phone test, 2026-11-11; decision 044), against the live stack (make up).

The start is the point on W 71st St nearest Broadway at W 79th St, a public crossing (never the phone's location).
- No route pads its distance with a short dead-end spur.
- Every route's name starts from its measured kind: a mostly retraced route is an out-and-back, never a loop.
- The TURN marker is at the main turnaround: for an out-and-back, about halfway.
- shape=loop is a hard rule: loops only, or the best other kind with a note saying so.
- Climb is read every 0.1 mi through a 2 m band, in whole meters (it read 130.5 m from summed tile noise).
"""

from functools import cache

import psycopg
import pytest

from api.constraints import RunConstraints
from api.engine import Engine, Start
from api.markers import spurs
from api.places import lookup
from api.shape import shape_metrics
from evals.routes.live import stack_problem
from etl.load import database_url

BROADWAY_79TH = (40.7800, -73.9800)
NAMES = {"loop": "Loop", "out_and_back": "Out-and-back", "lollipop": "Out-and-back with a loop"}


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


@cache
def built(shape: str):
    with psycopg.connect(database_url()) as conn:
        m = lookup("W 71st St", near=BROADWAY_79TH, conn=conn)[0]
    rc = RunConstraints(start_place={"kind": "place", "name": "W 71st St", "borough": "Manhattan", "lat": m.lat,
                                     "lon": m.lon}, distance_mi=5.0, shape=shape)
    return Engine(use_prior=False, anchor_fn=None).build(rc, Start(m.lat, m.lon, "W 71st St"), lambda e: None,
                                                         f"r_w71_{shape}")


def test_no_route_is_padded_with_a_spur():
    for shape in ("any", "loop"):
        for r in built(shape)["routes"]:
            assert spurs(r["geometry"]["coordinates"]) == [], (shape, r["label"])


def test_names_start_from_the_measured_kind():
    for shape in ("any", "loop"):
        final = built(shape)
        for r in final["routes"]:
            assert r["label"].startswith(NAMES[r["kind"]]), r["label"]
            retraced = shape_metrics(r["geometry"]["coordinates"]).retraced_pct
            assert (r["kind"] == "out_and_back") == (retraced >= 50), (r["kind"], retraced)
        props = final["route"]["features"][0]["properties"]
        assert props["name"] == props["label"] == final["routes"][0]["label"]


def test_the_turn_marker_is_at_the_main_turnaround():
    final = built("any")
    first = final["routes"][0]
    turns = [f["properties"]["along_m"] for f in final["route"]["features"]
             if f["properties"].get("feature") == "turnaround"]
    if first["kind"] == "out_and_back":
        half = first["distance"]["value"] * 1609.344 / 2
        assert len(turns) == 1 and abs(turns[0] - half) <= 0.1 * half, (turns, half)
    else:
        assert all(t > 400 for t in turns)


def test_loop_is_a_hard_rule():
    final = built("loop")
    kinds = [r["kind"] for r in final["routes"]]
    if any(n["key"] == "no_good_loop" for n in final["notes"]):
        assert kinds and "loop" not in kinds
    else:
        assert kinds and set(kinds) == {"loop"}


def test_climb_is_whole_meters_and_not_noise():
    for shape in ("any", "loop"):
        climb = built(shape)["route"]["features"][0]["properties"]["summary"]["climb"]
        assert isinstance(climb["value"], int) and climb["value"] <= 70, climb  # was 130.5 m, ground spans ~0-40 m
