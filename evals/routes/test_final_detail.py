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
