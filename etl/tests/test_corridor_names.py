import pytest

from etl.corridor_names import choose_name


def test_a_path_name_covering_enough_of_the_corridor_wins():
    assert choose_name([("Bobby Wagner Walk", 4000), ("East 96th Street", 200)], [], "waterfront", 6000) == \
        ("Bobby Wagner Walk", "way")


@pytest.mark.parametrize("street", ["Craig Road North", "57th Avenue", "Shore Boulevard", "Beach Patrol Road",
                                    "West Road", "East 82nd Street", "Gracie Place"])
def test_street_names_are_never_stretch_names(street):
    name, source = choose_name([(street, 5000)], [], "waterfront", 6000)
    assert name != street and source != "way"


def test_a_bridge_name_does_not_label_a_waterfront_corridor_it_is_only_part_of():
    name, _ = choose_name([("Manhattan Bridge Pedestrian Path", 2500), ("East River Greenway", 2000)], [],
                          "waterfront", 10000)
    assert name == "East River Greenway"


def test_a_corridor_that_is_mostly_a_bridge_keeps_the_bridge_name():
    assert choose_name([("Brooklyn Bridge Promenade", 3500)], [], "greenway", 4300) == \
        ("Brooklyn Bridge Promenade", "way")


def test_a_name_on_a_sliver_of_the_corridor_is_not_used():
    name, source = choose_name([("Pier 25 Walk", 300)], [], "waterfront", 6000)
    assert source != "way"


def test_falls_back_to_the_park_that_holds_most_of_the_corridor():
    assert choose_name([("57th Avenue", 2000)], [("Hunter's Point South Park", 1800), ("Gantry Plaza", 300)],
                       "waterfront", 2900) == ("Hunter's Point South Park waterfront", "park")


def test_a_park_holding_little_of_the_corridor_is_not_used():
    assert choose_name([], [("Tiny Park", 200)], "waterfront", 3000) == ("unnamed waterfront path", "none")


def test_park_drive_names_are_kept_for_park_drives():
    assert choose_name([("West Drive", 9000)], [("Central Park", 9900)], "park_drive", 9951) == ("West Drive", "way")


def test_a_street_called_drive_is_still_a_street_outside_park_drives():
    name, _ = choose_name([("Harlem River Drive", 3000)], [], "waterfront", 3500)
    assert name != "Harlem River Drive"


def test_a_greenway_named_after_a_road_is_still_a_greenway():
    assert choose_name([("Harlem River Drive Greenway", 3000)], [], "greenway", 3578) == \
        ("Harlem River Drive Greenway", "way")


def test_a_park_name_that_already_says_waterfront_is_not_repeated():
    assert choose_name([], [("Hunter's Point South Waterfront Park", 2500)], "waterfront", 2900) == \
        ("Hunter's Point South Waterfront Park", "park")
