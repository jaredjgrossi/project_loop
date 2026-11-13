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


# ---- the name from the main stretch (UI review: "East River Esplanade and beyond" is weak) ------------------------------


def stretch(name, kind, length_m):
    return {"name": name, "kind": kind, "length_m": length_m}


def test_a_route_is_named_after_the_stretch_it_runs_most():
    from api.naming import route_name
    stretches = [stretch("East 33rd Street", "street", 300), stretch("East River Esplanade", "corridor", 2800),
                 stretch("East 33rd Street", "street", 300)]
    assert route_name("out_and_back", "out-and-back on the waterfront", stretches) == \
        "Out-and-back on East River Esplanade"


def test_a_stretch_split_by_a_detour_still_adds_up():
    from api.naming import route_name
    stretches = [stretch("Hudson River Greenway", "corridor", 1000), stretch("West 23rd Street", "street", 900),
                 stretch("Hudson River Greenway", "corridor", 1100)]
    assert route_name("loop", "round trip, seed 3", stretches) == "Loop on Hudson River Greenway"


def test_a_park_is_run_through_not_on():
    from api.naming import route_name
    assert route_name("loop", "x", [stretch("Central Park", "park", 4000), stretch("Fifth Avenue", "street", 400)]) == \
        "Loop through Central Park"


def test_a_grid_loop_with_no_dominant_street_stays_on_the_street_grid():
    from api.naming import route_name
    sides = [stretch(n, "street", 800) for n in ("1st Avenue", "East 30th Street", "3rd Avenue", "East 24th Street")]
    assert route_name("loop", "rectangle 1:1, ++", sides) == "Loop on the street grid"


def test_a_street_that_carries_most_of_the_route_names_it():
    from api.naming import route_name
    assert route_name("out_and_back", "x", [stretch("Amsterdam Avenue", "street", 3000), stretch("W 72nd St", "street", 500)]) \
        == "Out-and-back on Amsterdam Avenue"


@pytest.mark.parametrize("name", ["unnamed path", "waterfront path", "waterfront path near East 23rd Street"])
def test_a_stretch_with_no_real_name_doesnt_name_the_route(name):
    from api.naming import route_name
    got = route_name("out_and_back", "out-and-back on the waterfront, heading 3 degrees", [stretch(name, "waterfront", 3000)])
    assert got == "Out-and-back on the waterfront"  # from the generator's label, as before


def test_no_stretches_falls_back_to_the_generators_label():
    from api.naming import route_name
    assert route_name("loop", "rectangle 1:1, ++", []) == "Loop on the street grid"
    assert route_name("a_to_b", "the shortest way", []) == "One way, the shortest way"


def test_a_one_way_run_names_its_main_stretch_too():
    from api.naming import route_name
    assert route_name("a_to_b", "along x", [stretch("East River Esplanade", "corridor", 4000)]) == \
        "One way on East River Esplanade"
