"""Along-avoids (step 8b, decision 036) on a made-up avenue: running along it is caught, crossing it isn't."""

import math

import pytest

from api.along import (ALONG_MAX_M, Along, custom_model, cut_stretch, longest_run_inside_m, router_areas, runs_along,
                       split_stretch)

LAT0, LON0 = 40.7400, -73.9780
M_LAT = 110_574
M_LON = 111_320 * math.cos(math.radians(LAT0))


def at(east_m: float, north_m: float) -> list[float]:
    return [LON0 + east_m / M_LON, LAT0 + north_m / M_LAT]


# An avenue running north for 1 km, in two OSM pieces, crossed by streets every 80 m.
AVENUE = Along("Test Ave", (tuple(at(0, n) for n in (0, 250, 500)), tuple(at(0, n) for n in (500, 750, 1000))),
               crossings=tuple(tuple(at(0, n)) for n in range(0, 1001, 80)))


def test_running_along_the_avenue_is_caught():
    route = [at(-300, 100), at(0, 100), at(0, 400), at(300, 400)]  # 300 m up the avenue
    assert longest_run_inside_m(route, AVENUE) == pytest.approx(300 + 2 * 20, abs=2)
    assert runs_along(route, [AVENUE]) == [AVENUE]


def test_crossing_the_avenue_is_fine():
    route = [at(-300, 100), at(300, 100), at(300, 180), at(-300, 180)]  # across and back
    assert longest_run_inside_m(route, AVENUE) == pytest.approx(40, abs=1)
    assert runs_along(route, [AVENUE]) == []


def test_a_diagonal_crossing_is_fine():
    route = [at(-100, 0), at(100, 60)]
    assert longest_run_inside_m(route, AVENUE) < ALONG_MAX_M


def test_a_parallel_street_a_block_away_is_fine():
    assert runs_along([at(80, 0), at(80, 1000)], [AVENUE]) == []


def test_router_areas_leave_the_crossings_open():
    areas = router_areas(AVENUE, "along_0")
    assert len(areas) >= 12 and all(f["geometry"]["type"] == "Polygon" for f in areas)
    from shapely.geometry import Point, shape
    for n in range(0, 1001, 80):  # no area at a crossing, where side streets meet the avenue
        assert not any(shape(f["geometry"]).contains(Point(at(0, n))) for f in areas)
    assert any(shape(f["geometry"]).contains(Point(at(0, 40))) for f in areas)  # mid-block is covered
    assert any(shape(f["geometry"]).contains(Point(at(15, 40))) for f in areas)  # and its sidewalk


def test_the_custom_model_names_every_area():
    model = custom_model([AVENUE])
    ids = {f["id"] for f in model["areas"]["features"]}
    (rule,) = model["priority"]  # one rule for all the areas (GraphHopper is three times faster)
    assert set(rule["if"].split(" || ")) == {f"in_{i}" for i in ids}
    assert custom_model([]) is None


@pytest.mark.parametrize("name, parts", [
    ("1st Ave, E 25th–E 34th St", ("1st Ave", "E 25th St", "E 34th St")),
    ("Broadway, E 14th-E 17th St", ("Broadway", "E 14th St", "E 17th St")),
    ("42nd St", ("42nd St", None, None)),
    ("1st Ave, E 25th St–E 34th St", ("1st Ave", "E 25th St", "E 34th St")),
])
def test_split_stretch(name, parts):
    assert split_stretch(name) == parts


def test_cut_stretch_between_two_cross_streets():
    cut = cut_stretch(AVENUE.lines, tuple(at(0, 200)), tuple(at(0, 700)))
    assert len(cut) == 1
    lats = [c[1] for c in cut[0]]
    assert min(lats) == pytest.approx(LAT0 + 200 / M_LAT, abs=1e-6)
    assert max(lats) == pytest.approx(LAT0 + 700 / M_LAT, abs=1e-6)
    stretch = Along("Test Ave, 200–700", cut)
    assert runs_along([at(0, 0), at(0, 150)], [stretch]) == []  # south of the stretch is fine
    assert runs_along([at(0, 300), at(0, 500)], [stretch]) == [stretch]


# ---- in the generator and the engine -------------------------------------------------------------------------------

from api.tests.test_a_to_b import GRID, KIPS, straight_route  # noqa: E402


def avenue_through(lat_lon, half_m=2000):
    """A made-up avenue running north-south through a point."""
    lat, lon = lat_lon
    return Along("Test Ave", (((lon, lat - half_m / M_LAT), (lon, lat + half_m / M_LAT)),),
                 crossings=tuple((lon, lat + k * 80 / M_LAT) for k in range(-25, 26)))


def test_a_route_along_the_street_is_rejected():
    from api.generate import _evaluate, generate_loops
    ave = avenue_through(KIPS)
    up_and_back = straight_route([KIPS, (KIPS[0] + 3000 / M_LAT, KIPS[1]), KIPS])  # up the avenue and back

    def job(rules):
        return [(0, lambda: _evaluate("t", None, "up the avenue", up_and_back, rules,
                                      allowed=("loop", "lollipop", "out_and_back")))]
    result = generate_loops(KIPS[0], KIPS[1], 4.0, GRID, route_fn=straight_route, round_trip_fn=None, top_n=10,
                            only_anchored=True, along=[ave], extra_jobs=job)
    assert result.candidates == [] and result.rejected["runs_along"] > 0


def test_the_engine_avoids_running_along_and_says_when_a_street_is_not_found():
    from api.engine import Engine, Start
    from api.tests.test_engine import engine, rc
    from api.generate import generate_loops
    from api.tests.test_a_to_b import area_route
    ave = avenue_through(KIPS)
    asked = {}

    def alongs_fn(names, near):
        asked["names"], asked["near"] = names, near
        return [ave], ["Nowhere St"]

    def routers_fn(zones, lights, closures, alongs=()):
        asked["router_alongs"] = alongs
        return straight_route, None, area_route
    e = engine(generate_loops, routers_fn=routers_fn, alongs_fn=alongs_fn)
    final = e.build(rc(distance_mi=3.0, avoid_places=[{"name": "Test Ave", "how": "along"},
                                                      {"name": "Nowhere St", "how": "along"},
                                                      {"name": "Times Square", "how": "area"}]),
                    Start(*KIPS, "x"), lambda ev: None, "r_a")
    assert asked["names"] == ["Test Ave", "Nowhere St"] and asked["router_alongs"] == [ave]
    assert final["routes"]
    assert all(not runs_along(r["geometry"]["coordinates"], [ave]) for r in final["routes"])
    assert [n["key"] for n in final["notes"] if n["key"] == "avoid_not_found"] == ["avoid_not_found"]
    assert "Nowhere St" in final["notes"][-1]["text"]
