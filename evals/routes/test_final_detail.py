"""The final event holds all three routes in full (decision 049), against the live stack (make up).

From the UI review: routes 2 and 3 had no stats, names were weak, the shape flag was missing, and the stretch list
named a path after the road beside it. Starts are public stand-ins (evals/routes/starts.json).
"""

import re
from functools import cache

import psycopg
import pytest

from api.constraints import RunConstraints
from api.engine import Engine, Start
from api.segments import route_stretches_and_pieces
from api.steps import MIN_STEP_M
from etl.load import database_url
from evals.routes.live import load_starts, stack_problem, top_loops

ROADISH = re.compile(r"\b(drive|dr|expressway|expy|parkway|pkwy|highway|hwy|boulevard|blvd|avenue|ave)\b", re.I)
SUMMARY_KEYS = {"distance", "kind", "waterfront_pct", "park_pct", "signalized_crossings", "lights_per_mile", "climb",
                "turnarounds", "way", "reason", "score", "rank"}


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


@cache
def built(shape="any", miles=3.0):
    s = load_starts()["kips-bay"]
    rc = RunConstraints(use_my_location=True, distance_mi=miles, shape=shape)
    return Engine(use_prior=False, anchor_fn=None).build(rc, Start(s["lat"], s["lon"], "Kips Bay"), lambda e: None,
                                                         f"r_fd_{shape}_{miles}")


def test_every_route_has_a_full_file_with_stats_a_way_and_a_reason():
    final = built()
    assert [r["rank"] for r in final["routes"]] == [1, 2, 3]
    for r in final["routes"]:
        props = r["file"]["features"][0]["properties"]
        summary = props["summary"]
        assert SUMMARY_KEYS <= set(summary), set(summary)
        assert summary["signalized_crossings"]["status"] == "measured" and summary["waterfront_pct"]["status"] == "measured"
        kinds = {f["properties"].get("feature") for f in r["file"]["features"][1:]}
        assert {"mile", "stretch", "piece"} <= kinds, kinds  # markers, stretches and pieces for every route
        assert summary["reason"]["source"] and (summary["reason"]["text"] is None or summary["reason"]["parts"])
    assert final["route"] == final["routes"][0]["file"]


def test_the_way_adds_up_to_the_route_and_names_the_turnaround():
    for r in built()["routes"]:
        summary = r["file"]["features"][0]["properties"]["summary"]
        way = summary["way"]
        assert way and all(w["name"] and w["kind"] and w["distance"]["status"] == "measured" for w in way)
        total = sum(w["distance"]["meters"] for w in way)
        assert total == pytest.approx(summary["distance"]["meters"], rel=0.03), (r["label"], total)
        if r["kind"] == "out_and_back":
            assert sum("turnaround" in w for w in way) == len(summary["turnarounds"]) >= 1, r["label"]


TYPE_WORDS = re.compile(r"out-and-back|\bloop\b|one way|lollipop|heading|degrees|both ways|\u00b0|rectangle|and beyond", re.I)


@pytest.mark.parametrize("shape, miles", [("any", 3.0), ("any", 6.0), ("loop", 4.0)])
def test_the_three_names_are_ones_a_runner_would_say(shape, miles):
    """Phone test 2026-11-13: "out-and-back on the waterfront, heading 175" and "out-and-back both ways on the
    waterfront". No route type or generator word, capitalized, short, and different for each of the three."""
    routes = built(shape, miles)["routes"]
    names = [r["label"] for r in routes]
    for r in routes:
        props = r["file"]["features"][0]["properties"]
        assert r["label"] == props["label"] == props["name"]  # one name everywhere
        assert not TYPE_WORDS.search(r["label"]), r["label"]
        assert not r["label"][0].islower() and len(r["label"]) <= 36, r["label"]
        assert not r["label"].endswith(("waterfront path", "unnamed path")), r["label"]
        assert "plan" not in props and "name_ladder" not in props  # the generator's words never reach the app
    assert len(set(names)) == len(names), names


MANEUVERS = {"start", "continue", "slight_left", "left", "sharp_left", "slight_right", "right", "sharp_right", "u_turn",
             "turnaround", "finish"}


def assert_steps_are_directions(r):
    """Decision 054: steps for the Directions list tile the route and say something a runner can do."""
    summary = r["file"]["features"][0]["properties"]["summary"]
    steps = summary["steps"]
    assert steps[0]["maneuver"] == "start" and steps[0]["from_meters"] == 0, r["label"]
    assert steps[-1]["maneuver"] == "finish" and steps[-1]["from_meters"] == summary["distance"]["meters"], r["label"]
    assert steps[-1]["distance"]["meters"] == 0 and steps[-1]["from_mile"] == summary["distance"]["value"]
    for i, (a, b) in enumerate(zip(steps, steps[1:])):
        assert a["index"] == i and a["maneuver"] in MANEUVERS
        assert a["from_meters"] + a["distance"]["meters"] == b["from_meters"], (r["label"], a, b)
        assert a["from_mile"] + a["distance"]["value"] == pytest.approx(b["from_mile"], abs=1e-9)
        assert a["status"] == "measured" and a["trust"] in ("verified", "listed", "seasonal_or_closed") and a["source"]
        if a["maneuver"] not in ("start", "turnaround"):
            assert a["distance"]["meters"] >= MIN_STEP_M, (r["label"], a)  # no crossing or curb jog is a step of its own
        if a["maneuver"] == "continue":
            assert a["street"] and a["street"] != steps[i - 1]["street"], (r["label"], a)  # onto a different street
    turns = [t["meters"] for t in summary["turnarounds"]]
    got = [x["from_meters"] for x in steps if x["maneuver"] == "turnaround"]
    assert len(got) == len(turns) and all(abs(g - t) <= 3 for g, t in zip(got, sorted(turns))), (r["label"], got, turns)
    assert summary["way"]  # older clients keep the stretch list


@pytest.mark.parametrize("shape, miles", [("any", 3.0), ("any", 6.0), ("loop", 4.0)])
def test_every_route_of_the_final_has_steps_that_tile_it(shape, miles):
    routes = built(shape, miles)["routes"]
    assert len(routes) == 3
    for r in routes:
        assert_steps_are_directions(r)


def test_a_one_way_run_through_central_park_has_steps_too():
    """Grand Army Plaza (a public landmark) to Harlem Meer: the shortest way, which runs through the park."""
    start, end = (40.7644, -73.9737), (40.7970, -73.9515)
    place = {"kind": "place", "name": "Harlem Meer", "borough": "Manhattan", "lat": end[0], "lon": end[1]}
    rc = RunConstraints(use_my_location=True, end_place=place)
    final = Engine(use_prior=False, anchor_fn=None).build(rc, Start(*start, "Grand Army Plaza"), lambda e: None,
                                                         "r_fd_park", end=end)
    assert final["routes"] and all(r["kind"] == "a_to_b" for r in final["routes"])
    for r in final["routes"]:
        assert_steps_are_directions(r)


def test_the_shape_flag_agrees_with_what_was_shown():
    for shape in ("any", "loop"):
        final = built(shape)
        kinds = {r["kind"] for r in final["routes"]}
        assert final["shape"]["requested"] == shape and set(final["shape"]["shown"]) == kinds
        assert final["shape"]["met"] == (shape == "any" or kinds == {"loop"})
        if not final["shape"]["met"]:
            assert final["notes"][0]["key"] == "no_good_loop"


@pytest.mark.parametrize("start, miles", [("upper-east-side", 3), ("upper-east-side", 6), ("astor-place", 6),
                                          ("kips-bay", 6)])
def test_a_path_or_waterfront_stretch_is_never_named_after_a_road(start, miles):
    with psycopg.connect(database_url()) as conn:
        for c in top_loops(start, miles, 3, use_prior=False):
            stretches, _ = route_stretches_and_pieces(conn, c.route.coordinates, c.route.elevation)
            for s in stretches:
                p = s["properties"]
                if p["kind"] in ("waterfront", "path"):
                    assert not ROADISH.search(p["name"]), (start, miles, c.label, p["kind"], p["name"], p["length_m"])
