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
