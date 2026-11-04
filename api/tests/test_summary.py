import math

import pytest

from api.constraints import DEFAULTS
from api.generate import Candidate
from api.markers import marker_features
from api.ranking import rank
from api.route_context import ContextScores
from api.routing import Route
from api.segments import Label, stretch_features
from api.shape import shape_metrics
from api.summary import route_summary

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * math.cos(math.radians(LAT0))

STREET = Label("street", "East 34th Street", "OSM way w1", "listed")
GREENWAY = Label("corridor", "East River Esplanade", "Loop corridor catalog #9 (OSM ways)", "listed")
LABELS = ["measured", "estimate", "not_scored", "provisional"]


def out_and_back():
    # 2.4 km out and 2.4 km back along one line: 4.8 km, a turnaround at 2.4 km.
    return [[LON0 + x / KX, LAT0] for x in list(range(0, 2401, 20)) + list(range(2380, -1, -20))]


def candidate(context=None):
    coords = out_and_back()
    shape = shape_metrics(coords)
    route = Route(distance_m=4800, time_s=3600, coordinates=coords)
    return Candidate("water_out_and_back", "test", route, shape, 81.7, -0.6, True, "out_and_back",
                     rank("out_and_back", shape, DEFAULTS, context), context)


def stretches(coords):
    labels = [STREET] * 20 + [GREENWAY] * 202 + [STREET] * 19  # 400 m, 4,040 m, 380 m: samples every 20 m
    comps = [{"waterfront": 0.0, "park": 0.0, "path": 0.0, "street": 400.0},
             {"waterfront": 2900.0, "park": 0.0, "path": 300.0, "street": 820.0},
             {"waterfront": 0.0, "park": 0.0, "path": 0.0, "street": 380.0}]
    return stretch_features(coords, labels, step_m=20, signals=[3, 6, 3], gains=[0.0, 2.0, 1.0], compositions=comps)


CONTEXT = ContextScores(park_pct=0.0, waterfront_pct=60.4, park_or_water_pct=60.4, crossings_per_mile=4.0,
                        signals_per_mile=1.8, familiar_pct=None, wait_s=194.4, wait_signals=12)
ELEVATION = {"status": "estimate", "source": "Terrain Tiles", "gain_m": 8.5}


def test_every_summary_value_has_a_trust_label():
    c = candidate(CONTEXT)
    s = route_summary(c, stretches(c.route.coordinates), marker_features(c.route.coordinates), ELEVATION)
    for key, v in s.items():
        if key == "kind":
            continue
        for item in v if isinstance(v, list) else [v]:
            assert item["status"] in LABELS, key
            assert item["status"] == "not_scored" or item["source"], key
    assert s["distance"]["value"] == 2.98 and s["distance"]["unit"] == "mi" and s["distance"]["status"] == "measured"
    assert s["distance"]["meters"] == pytest.approx(4800, abs=2) and s["distance"]["router_meters"] == 4800
    assert s["score"]["status"] == "provisional"


def test_shares_and_lights_are_the_sums_of_the_stretches():
    c = candidate(CONTEXT)
    s = route_summary(c, stretches(c.route.coordinates), [], ELEVATION)
    assert s["waterfront_pct"]["value"] == pytest.approx(100 * 2900 / 4800, abs=0.05)
    assert s["street_pct"]["value"] == pytest.approx(100 * 1600 / 4800, abs=0.05)
    # Four shares, each rounded to 0.1, add up to 100 within that rounding.
    assert sum(s[f"{k}_pct"]["value"] for k in ("waterfront", "park", "path", "street")) == pytest.approx(100, abs=0.2)
    assert s["signalized_crossings"]["value"] == 12
    assert s["lights_per_mile"]["value"] == pytest.approx(12 / (4800 / 1609.344), abs=0.05)
    # The ranking keeps its own input, each crosswalk once, and says so.
    assert s["ranking_signals_per_mile"]["value"] == 1.8 and "once" in s["ranking_signals_per_mile"]["counted"]


def test_estimates_are_labeled_and_the_turnaround_is_measured():
    c = candidate(CONTEXT)
    s = route_summary(c, [], marker_features(c.route.coordinates), ELEVATION)
    assert s["climb"] == {"value": 8.5, "unit": "m", "status": "estimate", "source": "Terrain Tiles"}
    assert s["wait_at_lights"]["status"] == "estimate" and s["wait_at_lights"]["value"] == 3.2
    (turn,) = s["turnarounds"]
    assert turn["status"] == "measured" and turn["value"] == pytest.approx(2400 / 1609.344, abs=0.03)


def test_missing_data_is_not_scored_with_a_reason_never_zero():
    c = candidate(None)
    s = route_summary(c, [], [], {"status": "not_scored"})
    for key in ("waterfront_pct", "street_pct", "lights_per_mile", "climb", "wait_at_lights", "crowds",
                "ranking_signals_per_mile"):
        assert s[key]["status"] == "not_scored" and s[key]["value"] is None and s[key]["reason"], key


def test_rank_says_best_of_how_many_distinct_routes():
    c = candidate(CONTEXT)
    s = route_summary(c, [], [], ELEVATION, rank=1, best_of=41)
    assert s["rank"]["value"] == 1 and s["rank"]["of"] == 41 and s["rank"]["status"] == "measured"
    assert route_summary(c, [], [], ELEVATION, rank=1, best_of=None)["rank"]["status"] == "not_scored"
