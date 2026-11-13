"""Turn-by-turn steps for the Directions list (decision 054): GraphHopper's turn signs, our own street names, folded
into the steps a runner would follow, tiling the route.

Routes here are walked on a flat grid in 20 m points (the same projection the mile and turnaround markers use), with the
instruction indexes GraphHopper would give them."""

import math

import pytest

from api.steps import MIN_STEP_M, maneuver_from_angle, route_steps

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574
SPACING = 20


def walk(legs):
    """[lon, lat] points for (bearing_deg, meters) legs from the origin, a point every 20 m and at each corner; also the
    index of the point at the end of each leg."""
    e = n = 0.0
    coords, corners = [[LON0, LAT0]], []
    for bearing, length in legs:
        dx, dy = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
        done = 0.0
        while done < length - 1e-6:
            done = min(length, done + SPACING)
            coords.append([LON0 + (e + dx * done) / KX, LAT0 + (n + dy * done) / KY])
        e, n = e + dx * length, n + dy * length
        corners.append(len(coords) - 1)
    return coords, corners


def total_of(coords):
    return round(sum(math.dist(((a[0] - coords[0][0]) * KX, (a[1] - LAT0) * KY),
                               ((b[0] - coords[0][0]) * KX, (b[1] - LAT0) * KY)) for a, b in zip(coords, coords[1:])))


def stretch(name, length_m, trust="listed", source="OSM way w1"):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": []},
            "properties": {"feature": "stretch", "name": name, "length_m": length_m,
                           "facts": [{"text": name, "source": source, "trust": trust}]}}


def steps_for(legs, instructions, stretches, turns=()):
    coords, corners = walk(legs)
    total = total_of(coords)
    return route_steps(coords, instructions(corners), stretches, list(turns), total), total


def assert_tiles(steps, total):
    assert steps[0]["from_meters"] == 0 and steps[0]["index"] == 0
    for a, b in zip(steps, steps[1:]):
        assert a["from_meters"] + a["distance"]["meters"] == b["from_meters"], (a, b)
        assert b["index"] == a["index"] + 1
        assert a["from_mile"] + a["distance"]["value"] == pytest.approx(b["from_mile"], abs=1e-9), (a, b)
    last = steps[-1]
    assert last["maneuver"] == "finish" and last["distance"]["meters"] == 0 and last["from_meters"] == total
    assert last["from_mile"] == round(total / 1609.344, 2)
    for s in steps:
        assert s["from_mile"] == round(s["from_meters"] / 1609.344, 2)
        assert s["distance"]["status"] == "measured" and s["distance"]["unit"] == "mi" and s["distance"]["source"]
        assert s["trust"] in ("verified", "listed", "seasonal_or_closed") and s["source"]
        assert set(s["point"]) == {"lat", "lon"}


# ---- the three kinds of route ---------------------------------------------------------------------------------------


def test_an_out_and_back_has_start_one_turnaround_and_finish_and_tiles():
    steps, total = steps_for([(90, 1000), (270, 1000)],
                             lambda c: [(0, 0), (5, c[0]), (-98, c[0]), (4, c[1])],
                             [stretch("East River Esplanade", 2000)], turns=[1000])
    assert [s["maneuver"] for s in steps] == ["start", "turnaround", "finish"]
    assert [s["street"] for s in steps] == ["East River Esplanade", "East River Esplanade", None]
    assert steps[1]["from_meters"] == 1000 and steps[1]["distance"]["meters"] == total - 1000
    assert_tiles(steps, total)


def test_a_loop_has_its_turns_in_order_and_tiles():
    steps, total = steps_for([(90, 400), (180, 400), (270, 400), (0, 400)],
                             lambda c: [(0, 0), (2, c[0]), (2, c[1]), (2, c[2]), (4, c[3])],
                             [stretch("Second Avenue", 400), stretch("East 30th Street", 400),
                              stretch("First Avenue", 400), stretch("East 34th Street", 400)])
    assert [(s["maneuver"], s["street"]) for s in steps] == [
        ("start", "Second Avenue"), ("right", "East 30th Street"), ("right", "First Avenue"),
        ("right", "East 34th Street"), ("finish", None)]
    assert [s["from_meters"] for s in steps] == [0, 400, 800, 1200, 1600]
    assert_tiles(steps, total)


def test_a_one_way_run_keeps_its_lefts_and_slight_rights():
    steps, total = steps_for([(90, 500), (0, 500), (30, 500)],
                             lambda c: [(0, 0), (-2, c[0]), (1, c[1]), (4, c[2])],
                             [stretch("A Street", 500), stretch("B Street", 500), stretch("C Street", 500)])
    assert [(s["maneuver"], s["street"]) for s in steps] == [
        ("start", "A Street"), ("left", "B Street"), ("slight_right", "C Street"), ("finish", None)]
    assert_tiles(steps, total)


def test_a_route_with_two_turnarounds_has_two_turnaround_steps():
    steps, total = steps_for([(90, 500), (270, 1000), (90, 500)],
                             lambda c: [(0, 0), (-98, c[0]), (-98, c[1]), (4, c[2])],
                             [stretch("The Walk", 2000)], turns=[500, 1500])
    assert [s["maneuver"] for s in steps] == ["start", "turnaround", "turnaround", "finish"]
    assert [s["from_meters"] for s in steps] == [0, 500, 1500, 2000]
    assert_tiles(steps, total)


# ---- GraphHopper's signs ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sign, bearing, maneuver", [
    (-3, 270, "sharp_left"), (-2, 0, "left"), (-1, 45, "slight_left"), (1, 135, "slight_right"), (2, 180, "right"),
    (3, 225, "sharp_right"), (-7, 45, "slight_left"), (7, 135, "slight_right"), (-98, 270, "u_turn"),
    (-8, 270, "u_turn"), (8, 270, "u_turn")])
def test_each_sign_is_one_maneuver(sign, bearing, maneuver):
    # A street name change at the turn, so a turn onto the same street isn't the thing under test.
    steps, total = steps_for([(90, 300), (bearing, 300)], lambda c: [(0, 0), (sign, c[0]), (4, c[1])],
                             [stretch("A Street", 300), stretch("B Street", 300)])
    assert [s["maneuver"] for s in steps] == ["start", maneuver, "finish"]


def test_a_via_point_is_not_a_step():
    steps, _ = steps_for([(90, 600)], lambda c: [(0, 0), (5, 15), (4, c[0])], [stretch("A Street", 600)])
    assert [s["maneuver"] for s in steps] == ["start", "finish"]


@pytest.mark.parametrize("degrees, maneuver", [
    (0, "continue"), (10, "continue"), (-10, "continue"), (20, "slight_right"), (-20, "slight_left"),
    (45, "slight_right"), (60, "right"), (-60, "left"), (100, "right"), (-100, "left"), (120, "sharp_right"),
    (-120, "sharp_left"), (165, "sharp_right"), (175, "u_turn"), (-175, "u_turn")])
def test_a_turn_measured_from_the_line_is_named_by_its_angle(degrees, maneuver):
    assert maneuver_from_angle(degrees) == maneuver


# ---- noise ---------------------------------------------------------------------------------------------------------------


def test_a_crossing_isnt_a_step():
    # East 300 m, a 15 m jog north to cross a street, east 300 m: GraphHopper says right, left; the runner went straight on.
    steps, total = steps_for([(90, 300), (0, 15), (90, 300)], lambda c: [(0, 0), (-2, c[0]), (2, c[1]), (4, c[2])],
                             [stretch("East 30th Street", 615)])
    assert [s["maneuver"] for s in steps] == ["start", "finish"]
    assert steps[0]["distance"]["meters"] == total
    assert_tiles(steps, total)


def test_a_crossing_before_a_real_turn_leaves_the_turn_and_not_the_crossing():
    steps, total = steps_for([(90, 300), (180, 15), (90, 100), (0, 400)],
                             lambda c: [(0, 0), (2, c[0]), (-2, c[1]), (-2, c[2]), (4, c[3])],
                             [stretch("East 30th Street", 415), stretch("First Avenue", 400)])
    assert [(s["maneuver"], s["street"]) for s in steps] == [
        ("start", "East 30th Street"), ("left", "First Avenue"), ("finish", None)]
    assert steps[1]["from_meters"] == 415
    assert_tiles(steps, total)


def test_a_jog_that_changes_the_heading_names_the_net_turn():
    # East 300, south 15, then 100 m south-east, then on: the folded right-hand bit must not leave a bare "left".
    steps, _ = steps_for([(90, 300), (180, 15), (0, 15), (90, 400)],
                         lambda c: [(0, 0), (2, c[0]), (-2, c[1]), (2, c[2]), (4, c[3])],
                         [stretch("East 30th Street", 730)])
    assert [s["maneuver"] for s in steps] == ["start", "finish"]  # straight on, before and after the jog


def test_a_step_under_the_minimum_joins_the_one_before():
    assert MIN_STEP_M == 50
    steps, total = steps_for([(90, 300), (0, 40), (90, 300)], lambda c: [(0, 0), (-2, c[0]), (2, c[1]), (4, c[2])],
                             [stretch("A Street", 300), stretch("B Street", 40), stretch("A Street", 300)])
    assert [s["maneuver"] for s in steps] == ["start", "finish"]
    assert_tiles(steps, total)


def test_the_first_step_stays_however_short():
    steps, total = steps_for([(90, 40), (0, 500)], lambda c: [(0, 0), (-2, c[0]), (4, c[1])],
                             [stretch("A Street", 40), stretch("B Street", 500)])
    assert [(s["maneuver"], s["distance"]["meters"]) for s in steps] == [("start", 40), ("left", 500), ("finish", 0)]


def test_a_short_first_stretch_doesnt_make_its_own_step():
    steps, _ = steps_for([(90, 30), (90, 800)], lambda c: [(0, 0), (4, c[1])],
                         [stretch("Side Street", 30), stretch("East River Esplanade", 800)])
    assert [s["maneuver"] for s in steps] == ["start", "finish"]
    assert steps[0]["street"] == "East River Esplanade"  # the street it mostly runs


def test_a_turn_onto_the_street_it_is_on_isnt_a_continue_step():
    steps, _ = steps_for([(90, 1200)], lambda c: [(0, 0), (0, 30), (4, c[0])], [stretch("The Esplanade", 1200)])
    assert [s["maneuver"] for s in steps] == ["start", "finish"]


# ---- streets and paths ---------------------------------------------------------------------------------------------------


def test_a_change_of_street_with_no_turn_is_a_continue_onto_it():
    steps, total = steps_for([(90, 1200)], lambda c: [(0, 0), (4, c[0])],
                             [stretch("East 34th Street", 600), stretch("East River Esplanade", 600, source="Loop corridor catalog")])
    assert [(s["maneuver"], s["street"], s["from_meters"]) for s in steps] == [
        ("start", "East 34th Street", 0), ("continue", "East River Esplanade", 600), ("finish", None, total)]
    assert steps[1]["source"] == "Loop corridor catalog" and steps[1]["trust"] == "listed"  # the name's own source
    assert_tiles(steps, total)


def test_a_path_is_named_after_itself_never_the_road_beside_it():
    steps, _ = steps_for([(90, 1000)], lambda c: [(0, 0), (4, c[0])], [stretch("waterfront path", 1000)])
    assert steps[0]["street"] == "waterfront path"


def test_a_turn_names_the_street_it_leads_onto_and_a_later_change_is_a_continue():
    steps, _ = steps_for([(90, 100), (0, 400)], lambda c: [(0, 0), (-2, c[0]), (4, c[1])],
                         [stretch("A Street", 100), stretch("B Street", 100), stretch("C Street", 300)])
    assert [(s["maneuver"], s["street"], s["from_meters"]) for s in steps] == [
        ("start", "A Street", 0), ("left", "B Street", 100), ("continue", "C Street", 200), ("finish", None, 500)]


def test_a_stretch_under_the_minimum_between_two_streets_is_part_of_the_step_before():
    steps, total = steps_for([(90, 1000)], lambda c: [(0, 0), (4, c[0])],
                             [stretch("A Street", 600), stretch("Crossing Street", 30), stretch("C Street", 370)])
    assert [(s["maneuver"], s["street"], s["from_meters"]) for s in steps] == [
        ("start", "A Street", 0), ("continue", "C Street", 630), ("finish", None, total)]


def test_a_step_takes_the_street_it_runs_most():
    # A turn at 100 m, then 20 m on the cross street's sidewalk before the long street begins.
    steps, _ = steps_for([(90, 100), (0, 420)], lambda c: [(0, 0), (-2, c[0]), (4, c[1])],
                         [stretch("A Street", 100), stretch("Sidewalk Street", 20), stretch("C Street", 400)])
    assert [(s["maneuver"], s["street"]) for s in steps] == [("start", "A Street"), ("left", "C Street"), ("finish", None)]


# ---- turnarounds -----------------------------------------------------------------------------------------------------------


def test_a_turnaround_lands_in_exactly_one_step_boundary():
    # GraphHopper has a left 10 m before the turn, a U-turn at it and a right 20 m after: the runner turns once.
    coords, _ = walk([(90, 1000), (270, 1000)])
    turn_idx = 50
    steps = route_steps(coords, [(0, 0), (-2, turn_idx - 1), (5, turn_idx), (-98, turn_idx), (2, turn_idx + 1), (4, 100)],
                        [stretch("East River Esplanade", 2000)], [1000], total_of(coords))
    assert [s["maneuver"] for s in steps] == ["start", "turnaround", "finish"]
    near = [s for s in steps if abs(s["from_meters"] - 1000) <= 60]
    assert len(near) == 1 and near[0]["from_meters"] == 1000


def test_a_u_turn_away_from_a_turnaround_stays_a_u_turn():
    steps, _ = steps_for([(90, 500), (270, 100), (90, 400)],
                         lambda c: [(0, 0), (-98, c[0]), (2, c[1]), (4, c[2])], [stretch("A Street", 1000)])
    assert "u_turn" in [s["maneuver"] for s in steps]


# ---- the route itself ----------------------------------------------------------------------------------------------------------


def test_the_finish_is_at_the_end_of_the_route_and_the_start_at_its_start():
    coords, _ = walk([(90, 600)])
    steps = route_steps(coords, [(0, 0), (4, 30)], [stretch("A Street", 600)], [], total_of(coords))
    assert steps[0]["point"] == pytest.approx({"lat": LAT0, "lon": LON0}) and steps[0]["maneuver"] == "start"
    assert steps[-1]["point"]["lon"] == pytest.approx(coords[-1][0]) and steps[-1]["point"]["lat"] == pytest.approx(coords[-1][1])
    assert steps[-1]["street"] is None


def test_a_step_carries_its_maneuver_source_and_a_point_on_the_route():
    coords, _ = walk([(90, 500), (0, 500)])
    steps = route_steps(coords, [(0, 0), (-2, 25), (4, 50)], [stretch("A", 500), stretch("B", 500)], [], total_of(coords))
    turn = steps[1]
    assert turn["point"]["lon"] == pytest.approx(coords[25][0], abs=1e-5) and turn["maneuver_source"]
    assert turn["distance"]["meters"] == 500 and turn["distance"]["value"] == 0.31


def test_no_instructions_means_no_steps():
    coords, _ = walk([(90, 600)])
    assert route_steps(coords, None, [stretch("A", 600)], [], total_of(coords)) is None
    assert route_steps(coords, [], [stretch("A", 600)], [], total_of(coords)) is None
