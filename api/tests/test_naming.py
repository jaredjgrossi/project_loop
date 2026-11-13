"""Route names from the measured kind (decision 044)."""

import pytest

from api.naming import display_name


@pytest.mark.parametrize("kind, label, name", [
    ("lollipop", "loop on Riverside Walk, heading 19 degrees", "Out-and-back with a loop on Riverside Walk"),
    ("out_and_back", "loop on Riverside Walk, heading 19 degrees", "Out-and-back on Riverside Walk"),
    ("out_and_back", "out-and-back through Central Park, heading 44 degrees", "Out-and-back through Central Park"),
    ("loop", "rectangle 1:1, ++", "Loop on the street grid"),
    ("out_and_back", "out-and-back on West Drive and beyond, heading 45 degrees", "Out-and-back on West Drive"),
    ("a_to_b", "the shortest way", "One way, the shortest way"),
    ("a_to_b", "along Domino Park waterfront to the end", "One way along Domino Park waterfront"),
    ("loop", "round trip, seed 3", "Loop"),
])
def test_the_name_starts_from_the_kind(kind, label, name):
    assert display_name(kind, label) == name


@pytest.mark.parametrize("kind", ["out_and_back", "lollipop", "a_to_b"])
def test_a_route_that_isnt_a_loop_is_never_called_one(kind):
    assert not display_name(kind, "loop on Riverside Walk, heading 19 degrees").startswith("Loop")


# ---- the name a runner would say (phone test 2026-11-13) ---------------------------------------------------------------

import math

from api.naming import MAX_NAME, compass, cross_label, name_ladder, settle_names, short

LAT0, LON0 = 40.74, -73.98
KX, KY = 111_320 * math.cos(math.radians(LAT0)), 110_574
INTERNAL = ("Out-and-back", "Loop", "One way", "heading", "degrees", "both ways", "out-and-back", "loop", "rectangle")


def line(points_m):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in points_m]


def out_and_back(bearing_deg=0.0, reach_m=2400):
    dx, dy = math.sin(math.radians(bearing_deg)), math.cos(math.radians(bearing_deg))
    way = [(dx * d, dy * d) for d in range(0, reach_m + 1, 40)]
    return line(way + way[-2::-1])


def around(clockwise_, r=500):
    pts = [(r * math.sin(a), r * math.cos(a)) for a in (i * math.pi / 30 for i in range(61))]
    return line(pts if clockwise_ else pts[::-1])


def stretch(name, kind, length_m):
    return {"name": name, "kind": kind, "length_m": length_m}


ESPLANADE = [stretch("East 33rd Street", "street", 300), stretch("East River Esplanade", "corridor", 4200),
             stretch("East 33rd Street", "street", 300)]


def cross(name):
    return lambda lat, lon, exclude: name


def first(*a, **kw):
    return name_ladder(*a, **kw)[0]


def test_an_out_and_back_is_named_by_its_stretch_heading_and_turnaround():
    assert first("out_and_back", "out-and-back on the waterfront, heading 175 degrees", out_and_back(20), ESPLANADE,
                 cross("East 34th Street")) == "East River Esplanade, north to 34th"


@pytest.mark.parametrize("bearing, word", [(0, "north"), (29, "north"), (100, "east"), (180, "south"), (200, "south"),
                                           (270, "west"), (330, "north")])
def test_the_heading_is_one_of_four_words(bearing, word):
    assert compass(bearing) == word


def test_a_run_south_says_south_and_names_where_it_ends():
    got = first("a_to_b", "along the greenway", out_and_back(190)[:61], [stretch("Hudson Greenway", "corridor", 2400)],
                cross("Canal Street"))
    assert got == "Hudson Greenway, south to Canal"


def test_a_name_that_would_run_long_drops_the_turnaround_before_the_heading():
    got = first("a_to_b", "x", out_and_back(190)[:61], [stretch("Hudson River Greenway", "corridor", 2400)],
                cross("Canal Street"))
    assert got == "Hudson River Greenway, south"  # "..., south to Canal" is 37 characters


@pytest.mark.parametrize("kind, label", [
    ("out_and_back", "out-and-back on the waterfront, heading 175 degrees"),
    ("out_and_back", "out-and-back both ways on the waterfront"),
    ("lollipop", "loop on Riverside Walk, heading 19 degrees"),
    ("loop", "rectangle 1:1, ++"),
    ("a_to_b", "the shortest way"),
])
def test_no_name_has_the_route_type_or_a_generator_word(kind, label):
    for stretches in ([], ESPLANADE):
        for name in name_ladder(kind, label, out_and_back(100), stretches, cross("East 34th Street"), 3.1):
            assert not any(w in name for w in INTERNAL), name
            assert name[0].isupper() and len(name) <= MAX_NAME, name


def test_a_loop_says_which_way_round_it_runs():
    park = [stretch("Central Park", "park", 3000)]
    assert first("loop", "x", around(True), park) == "Central Park, clockwise"
    assert first("loop", "x", around(False), park) == "Central Park, counterclockwise"


def test_a_loop_on_two_streets_names_both():
    sides = [stretch("1st Avenue", "street", 1400), stretch("East 30th Street", "street", 1100),
             stretch("3rd Avenue", "street", 200)]
    assert first("loop", "rectangle 1:1, ++", around(True), sides) == "1st Ave & E 30th St, clockwise"


def test_a_grid_loop_where_no_street_carries_it_names_the_two_it_runs_most():
    sides = [stretch("1st Avenue", "street", 1000), stretch("East 30th Street", "street", 900),
             stretch("2nd Avenue", "street", 900), stretch("East 24th Street", "street", 900)]
    assert first("loop", "rectangle 1:1, ++", around(True), sides) == "1st Ave & E 30th St, clockwise"


def test_the_heading_is_from_where_the_route_joins_its_stretch_not_from_the_start():
    # Starts 2 km west of the river, runs east to the esplanade, then 800 m north along it and back. From the start the
    # far point is east-north-east (bearing 68), but the run along the esplanade heads north.
    way = [(d, 0) for d in range(0, 2001, 40)] + [(2000, d) for d in range(40, 801, 40)]
    coords = line(way + way[-2::-1])
    esp = {"name": "East River Esplanade", "kind": "corridor", "length_m": 3000, "from_mile": 2000 / 1609.344}
    street = stretch("Avenue C", "street", 2000)
    assert first("out_and_back", "x", coords, [street, esp], cross("East 34th Street")) == \
        "East River Esplanade, north to 34th"
    assert compass(68) == "east"  # the start-to-far bearing would have said "east"


def test_the_street_the_route_turns_at_is_not_the_stretch_it_runs():
    seen = []
    first("out_and_back", "x", out_and_back(0), ESPLANADE, lambda lat, lon, exclude: seen.append(exclude))
    assert seen == ["East River Esplanade"]


def test_without_a_cross_street_it_still_says_which_way():
    assert first("out_and_back", "x", out_and_back(0), ESPLANADE, cross(None)) == "East River Esplanade, north"
    assert first("out_and_back", "x", out_and_back(0), ESPLANADE) == "East River Esplanade, north"


def test_a_run_that_stays_near_its_start_has_no_direction():
    assert first("out_and_back", "x", out_and_back(0, reach_m=200), ESPLANADE, cross("East 34th Street")) == \
        "East River Esplanade"


@pytest.mark.parametrize("name", ["unnamed path", "waterfront path", "waterfront path near East 23rd Street"])
def test_a_stretch_with_no_real_name_doesnt_name_the_route(name):
    got = first("out_and_back", "out-and-back on the waterfront, heading 3 degrees", out_and_back(0),
                [stretch(name, "waterfront", 3000)], cross("East 23rd Street"))
    assert got == "Waterfront, north to 23rd"  # the generator's place, as a runner says it


def test_a_grid_loop_with_nothing_to_name_it_says_the_street_grid():
    assert first("loop", "rectangle 1:1, ++", around(False), []) == "Street grid, counterclockwise"


def test_a_name_too_long_is_shortened_not_cut_mid_word():
    long = [stretch("Brooklyn Bridge Park Greenway Extension Avenue", "corridor", 4000)]
    for name in name_ladder("out_and_back", "x", out_and_back(0), long, cross("East 34th Street"), 3.1):
        assert len(name) <= MAX_NAME


@pytest.mark.parametrize("street, said", [("East 34th Street", "34th"), ("West 72nd Street", "72nd"),
                                          ("1st Avenue", "1st Ave"), ("Canal Street", "Canal"), ("West Street", "West"),
                                          ("Houston Street", "Houston"), ("Avenue of the Americas", "Avenue of the Americas")])
def test_a_cross_street_as_a_runner_says_it(street, said):
    assert cross_label(street) == said


def test_short_street_words():
    assert short("East 30th Street") == "E 30th St" and short("Lexington Avenue") == "Lexington Ave"
    assert short("East River Esplanade") == "East River Esplanade"


# ---- three routes, three names ------------------------------------------------------------------------------------------


def file_with(ladder):
    return {"features": [{"properties": {"name": ladder[0], "label": ladder[0], "plan": "internal", "name_ladder": ladder}}]}


def names(files):
    return [f["features"][0]["properties"]["name"] for f in files]


def test_routes_that_would_share_a_name_are_told_apart_by_distance():
    files = [file_with(["East River Esplanade, north to 34th", "East River Esplanade, 3.1 mi"]),
             file_with(["East River Esplanade, north to 34th", "East River Esplanade, 3.0 mi"]),
             file_with(["Central Park, clockwise", "Central Park, 3.1 mi"])]
    settle_names(files)
    assert names(files) == ["East River Esplanade, north to 34th", "East River Esplanade, 3.0 mi", "Central Park, clockwise"]


def test_the_last_resort_is_a_number_and_the_names_are_always_distinct():
    files = [file_with(["A, north", "A, 3.1 mi"]) for _ in range(4)]
    settle_names(files)
    assert names(files) == ["A, north", "A, 3.1 mi", "A, north (2)", "A, north (3)"]
    assert len(set(names(files))) == 4


def test_the_label_matches_the_name_and_the_generators_plan_is_not_sent():
    files = [file_with(["Central Park, clockwise"])]
    settle_names(files)
    props = files[0]["features"][0]["properties"]
    assert props["label"] == props["name"] == "Central Park, clockwise"
    assert "plan" not in props and "name_ladder" not in props


def test_a_numbered_name_still_fits():
    files = [file_with(["X" * MAX_NAME]) for _ in range(2)]
    settle_names(files)
    assert all(len(n) <= MAX_NAME for n in names(files)) and len(set(names(files))) == 2
