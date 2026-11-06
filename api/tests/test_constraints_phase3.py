"""Phase 3 additions to RunConstraints (decision 027): place refs for start, end and via; hills; past-route reuse;
a planned second run; avoids with along/area; contract source keys (said, preset, default, usual); and the list of
what the engine can't build yet, so nothing is quietly dropped (product rule 3)."""

from datetime import date

import pytest
from pydantic import ValidationError

from api.constraints import (AvoidPlace, PlaceRef, RunConstraints, field_sources, request_items, resolve_preferences,
                             unsupported, with_default_date)

PENN = {"kind": "place", "name": "New York Penn Station", "borough": "Manhattan", "lat": 40.7502, "lon": -73.9928,
        "source": "OpenStreetMap", "trust": "listed"}
MCCARREN = {"kind": "place", "name": "McCarren Park", "borough": "Brooklyn", "lat": 40.7204, "lon": -73.9512,
            "source": "OpenStreetMap", "trust": "listed"}
HOME = {"kind": "saved", "id": "home"}


def here(**kw):
    return RunConstraints(use_my_location=True, **kw)


# ---- place refs -------------------------------------------------------------------------------------------------

def test_a_place_or_address_ref_needs_name_borough_and_coordinates():
    assert PlaceRef(**PENN).borough == "Manhattan"
    for missing in ("name", "borough", "lat", "lon"):
        with pytest.raises(ValidationError):
            PlaceRef(**{k: v for k, v in PENN.items() if k != missing})
    addr = PlaceRef(kind="address", name="11 Madison Ave", borough="Manhattan", lat=40.7415, lon=-73.9865,
                    source="NYC GeoSearch", trust="listed")
    assert addr.kind == "address"


def test_a_saved_ref_needs_an_id_and_may_wait_for_coordinates():
    assert PlaceRef(**HOME).id == "home"
    with pytest.raises(ValidationError):
        PlaceRef(kind="saved")


def test_exactly_one_start_counting_start_place():
    assert RunConstraints(start_place=PENN, distance_mi=6).start_place.name == "New York Penn Station"
    with pytest.raises(ValidationError, match="exactly one start"):
        RunConstraints(start_place=PENN, use_my_location=True, distance_mi=6)
    with pytest.raises(ValidationError, match="exactly one start"):
        RunConstraints(start_place=PENN, start_address="446 3rd Ave, 10016", distance_mi=6)


def test_end_and_via_places():
    c = here(distance_mi=8, end_place=MCCARREN, via_places=[PENN])
    assert c.end_place.borough == "Brooklyn" and [v.name for v in c.via_places] == ["New York Penn Station"]


# ---- distance ---------------------------------------------------------------------------------------------------

def test_distance_may_be_left_out_only_when_an_end_is_given():
    assert here(end_place=MCCARREN).distance_mi is None
    with pytest.raises(ValidationError, match="distance"):
        here()
    with pytest.raises(ValidationError, match="distance"):
        here(via_places=[PENN])  # via alone doesn't define a length


def test_amenity_past_the_end_is_only_checked_with_a_distance():
    assert here(end_place=MCCARREN, amenities=[{"kind": "restroom", "at_mile": 3}]).amenities[0].at_mile == 3
    with pytest.raises(ValidationError, match="past the end"):
        here(distance_mi=2, amenities=[{"kind": "restroom", "at_mile": 3}])


# ---- avoids, hills, reuse, planned ------------------------------------------------------------------------------

def test_avoid_names_become_area_avoids_and_streets_can_be_along():
    c = here(distance_mi=3, avoid_places=["Times Square", {"name": "42nd St", "how": "along"}])
    assert c.avoid_places == [AvoidPlace(name="Times Square", how="area"), AvoidPlace(name="42nd St", how="along")]
    with pytest.raises(ValidationError):
        here(distance_mi=3, avoid_places=[{"name": "42nd St", "how": "near"}])


def test_hills_is_a_preference_that_defaults_to_dont_mind():
    assert resolve_preferences(here(distance_mi=6)).values["hills"] == "dont_mind"
    p = resolve_preferences(here(distance_mi=6, hills="avoid"))
    assert (p.values["hills"], p.sources["hills"]) == ("avoid", "said")
    with pytest.raises(ValidationError):
        here(distance_mi=6, hills="steep")


def test_reverse_needs_a_route_to_reverse():
    assert here(reuse_route_id="rt_a", reverse=True).reverse
    with pytest.raises(ValidationError, match="reverse"):
        here(distance_mi=3, reverse=True)


def test_a_reused_route_brings_its_own_distance():
    assert here(reuse_route_id="rt_a").distance_mi is None


def test_planned_run_is_a_whole_request_for_its_day():
    c = here(distance_mi=3.11, start_time="20:00",
             planned={"start_place": HOME, "distance_mi": 10, "start_date": date(2026, 11, 7), "start_time": "07:00",
                      "sources": {"start_time": "usual", "start_place": "default"}})
    assert c.planned.start_place.id == "home" and c.planned.start_date == date(2026, 11, 7)
    with pytest.raises(ValidationError, match="day"):
        here(distance_mi=3, planned={"start_place": HOME, "distance_mi": 10})
    with pytest.raises(ValidationError, match="planned"):
        here(distance_mi=3, planned={"start_place": HOME, "distance_mi": 10, "start_date": date(2026, 11, 7),
                                     "planned": {"start_place": HOME, "distance_mi": 5,
                                                 "start_date": date(2026, 11, 8)}})


# ---- sources ----------------------------------------------------------------------------------------------------

def test_sources_use_the_contract_keys():
    c = here(distance_mi=3.1, crowds="avoid", sources={"distance_mi": "usual", "use_my_location": "default"})
    s = field_sources(c)
    assert s["distance_mi"] == "usual" and s["use_my_location"] == "default" and s["crowds"] == "said"
    assert "lights" not in s  # preferences left unstated are not "set"
    with pytest.raises(ValidationError):
        here(distance_mi=3, sources={"distance_mi": "you said"})
    with pytest.raises(ValidationError, match="unknown field"):
        here(distance_mi=3, sources={"miles": "usual"})


def test_preset_preferences_report_preset():
    p = resolve_preferences(here(distance_mi=5, mode="training"))
    assert p.sources["lights"] == "preset" and p.sources["hills"] == "preset"


def test_sources_survive_a_round_trip_through_json():
    """Chip edits send constraints back from the phone (contract): where each field came from must come back too."""
    c = with_default_date(here(distance_mi=3.1, start_time="07:00", sources={"distance_mi": "usual"}),
                          now=__import__("datetime").datetime(2026, 11, 3, 6, 40))
    back = RunConstraints.model_validate_json(c.model_dump_json())
    assert field_sources(back)["start_date"] == "default" and field_sources(back)["distance_mi"] == "usual"
    assert field_sources(back)["start_time"] == "said"


def test_planned_sources_are_dotted():
    c = here(distance_mi=3.11, planned={"start_place": HOME, "distance_mi": 10, "start_date": date(2026, 11, 7),
                                        "start_time": "07:00", "sources": {"start_time": "usual",
                                                                           "start_place": "default"}})
    s = field_sources(c)
    assert s["planned.start_time"] == "usual" and s["planned.start_place"] == "default"
    assert s["planned.distance_mi"] == "said"


# ---- the route file's request list ------------------------------------------------------------------------------

def test_request_items_keep_their_shape_and_add_the_new_fields():
    c = here(distance_mi=8, end_place=MCCARREN, via_places=[PENN], hills="avoid", sources={"distance_mi": "usual"})
    items = request_items(c)
    assert all(set(i) == {"key", "title", "value", "origin"} for i in items)
    by_key = {i["key"]: i for i in items}
    assert by_key["end"]["value"] == "McCarren Park, Brooklyn"  # the chip always names the borough (R19)
    assert by_key["via"]["value"] == "New York Penn Station, Manhattan"
    assert by_key["hills"]["origin"] == "you said" and by_key["distance"]["origin"] == "your usual"
    assert by_key["start"]["value"] == "your location"


def test_request_items_for_reuse():
    by_key = {i["key"]: i for i in request_items(here(reuse_route_id="rt_a", reverse=True,
                                                      sources={"reuse_route_id": "usual"}))}
    assert by_key["reuse"]["origin"] == "your usual" and by_key["reverse"]["value"] == "other direction"
    assert by_key["distance"]["value"] == "the route's"


# ---- what the engine can't build yet ----------------------------------------------------------------------------

def test_unsupported_lists_every_phase3_field_the_engine_cannot_build_yet():
    assert unsupported(here(distance_mi=3)) == []
    assert unsupported(here(distance_mi=3, hills="dont_mind")) == []
    c = here(distance_mi=8, end_place=MCCARREN, via_places=[PENN], hills="avoid",
             avoid_places=[{"name": "42nd St", "how": "along"}], reuse_route_id="rt_a",
             planned={"start_place": HOME, "distance_mi": 10, "start_date": date(2026, 11, 7)})
    assert unsupported(c) == ["end_place", "via_places", "hills", "avoid_along", "reuse_route_id", "planned"]
