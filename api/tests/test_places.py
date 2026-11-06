"""Place names: normalizing, street bases, display names, crossings and grouping (Phase 3, step 2). No database;
the lookups against the loaded table are in evals/places/."""

import pytest

from api.places import (PlaceMatch, display_name, group_ids, is_streetlike, normalize, pick_by_borough, split_crossing,
                        street_base)


@pytest.mark.parametrize("raw, want", [
    ("East 42nd Street", "e 42nd st"),
    ("E. 42nd St", "e 42nd st"),
    ("42 St", "42nd st"),
    ("86 St (Q)", "86th st"),
    ("First Avenue", "1st ave"),
    ("1st Ave", "1st ave"),
    ("West 23 Street", "w 23rd st"),
    ("East 11th Street", "e 11th st"),
    ("102 St", "102nd st"),
    ("113 Street", "113th st"),
    ("Central Park South", "central park s"),
    ("34th Street–Penn Station", "34th st penn station"),
    ("34 St-Penn Station (A,C,E)", "34th st penn station"),
    ("The Reservoir", "reservoir"),
    ("St. Mark's Place", "st marks pl"),
    ("Frederick Douglass Boulevard", "frederick douglass blvd"),
    ("  McCarren   Park ", "mccarren park"),
    ("Union Square", "union sq"),
])
def test_normalize(raw, want):
    assert normalize(raw) == want


def test_numbers_not_on_a_street_keep_their_form():
    assert normalize("Pier 45") == "pier 45"
    assert normalize("PS 116") == "ps 116"


@pytest.mark.parametrize("raw, want", [
    ("East 42nd Street", "42nd st"),
    ("West 86th Street", "86th st"),
    ("86th Street", "86th st"),
    ("South Street", "s st"),  # nothing left but the suffix: keep the direction
    ("North Moore Street", "moore st"),
    ("Central Park South", "central park s"),
])
def test_street_base_drops_a_leading_direction(raw, want):
    assert street_base(normalize(raw)) == want


@pytest.mark.parametrize("raw, want", [
    ("East 42nd Street", "E 42nd St"),
    ("First Avenue", "1st Ave"),
    ("Central Park West", "Central Park West"),
    ("Hudson River Greenway", "Hudson River Greenway"),
    ("Frederick Douglass Boulevard", "Frederick Douglass Blvd"),
])
def test_display_name(raw, want):
    assert display_name(raw) == want


@pytest.mark.parametrize("q, want", [
    ("1st Ave & E 23rd St", ("1st ave", "e 23rd st")),
    ("1st and 23rd", ("1st", "23rd")),
    ("5th Ave and E 86th St", ("5th ave", "e 86th st")),
    ("McCarren Park", None),
    ("&", None),
])
def test_split_crossing(q, want):
    assert split_crossing(q) == want


def test_streetlike():
    assert is_streetlike("86th st") and is_streetlike("central park s") is False
    assert is_streetlike("e 42nd st") and not is_streetlike("penn station")


def test_group_ids_joins_pairs_transitively():
    assert group_ids([1, 2, 3, 4, 5], [(1, 2), (2, 3), (4, 4)]) == [[1, 2, 3], [4], [5]]


def _m(borough, distance_m=None, name="42nd St"):
    return PlaceMatch(name=name, kind="street", borough=borough, lat=0, lon=0, matched=name, source="OpenStreetMap",
                      distance_m=distance_m)


def test_pick_one_match_is_that_match():
    assert pick_by_borough([_m("Queens")], "Manhattan").borough == "Queens"


def test_pick_prefers_the_reference_borough():
    assert pick_by_borough([_m("Brooklyn", 900), _m("Manhattan", 5000)], "Manhattan").borough == "Manhattan"


def test_pick_nearest_within_3_km_when_the_others_are_farther():
    found = [_m("Manhattan", 900), _m("Queens", 4000), _m("Brooklyn", 9000)]
    assert pick_by_borough(found, "Bronx").borough == "Manhattan"
    assert pick_by_borough(found).borough == "Manhattan"


def test_pick_asks_when_two_are_within_3_km_or_none_is():
    assert pick_by_borough([_m("Manhattan", 900), _m("Queens", 2500)]) is None
    assert pick_by_borough([_m("Manhattan", 3500), _m("Queens", 4000)]) is None
    assert pick_by_borough([_m("Manhattan"), _m("Queens")]) is None  # no distances: ask


def test_pick_applies_nearest_inside_the_reference_borough():
    found = [_m("Manhattan", 500, "a"), _m("Manhattan", 4000, "b"), _m("Brooklyn", 300, "c")]
    assert pick_by_borough(found, "Manhattan").name == "a"
