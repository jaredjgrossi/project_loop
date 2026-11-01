import math

import pytest

from api.segments import Label, merge_stretches, stretch_features

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574

STREET = Label("street", "East 34th Street", "OSM way w1", "listed")
GREENWAY = Label("corridor", "East River Greenway", "Loop corridor catalog #9 (OSM ways)", "listed")
PARK = Label("park", "Stuyvesant Cove Park", "OSM park area a7", "listed")


def test_consecutive_samples_with_the_same_label_make_one_stretch():
    labels = [STREET] * 10 + [GREENWAY] * 30 + [STREET] * 10
    stretches = merge_stretches(labels, step_m=20)
    assert [(s.label.name, s.start, s.end) for s in stretches] == [
        ("East 34th Street", 0, 10), ("East River Greenway", 10, 40), ("East 34th Street", 40, 50)]


def test_a_short_blip_is_absorbed_into_the_stretch_around_it():
    # 60 m in a park while on the greenway is not its own stretch.
    labels = [GREENWAY] * 20 + [PARK] * 3 + [GREENWAY] * 20
    stretches = merge_stretches(labels, step_m=20)
    assert len(stretches) == 1 and stretches[0].label == GREENWAY


def test_a_short_first_stretch_joins_the_next():
    labels = [STREET] * 2 + [GREENWAY] * 30
    assert [s.label for s in merge_stretches(labels, step_m=20)] == [GREENWAY]


def test_stretch_features_carry_miles_name_kind_and_facts_with_source_and_trust():
    coords = [[LON0 + x / KX, LAT0] for x in range(0, 1001, 20)]  # 1 km, a sample every 20 m
    labels = [STREET] * 15 + [GREENWAY] * 36
    feats = stretch_features(coords, labels, step_m=20, signals=[1, 0], gains=[0.0, 2.5],
                             extra_facts=[[], [{"text": "Known gap nearby", "source": "corridor_gaps #1", "trust": "listed"}]])
    assert [f["properties"]["name"] for f in feats] == ["East 34th Street", "East River Greenway"]
    first, second = (f["properties"] for f in feats)
    assert first["from_mile"] == 0 and second["to_mile"] == pytest.approx(1000 / 1609.344, abs=0.02)
    assert second["kind"] == "corridor" and second["signals"] == {"value": 0, "status": "measured"}
    assert second["elevation_gain_m"] == {"value": 2.5, "status": "estimate"}
    for f in feats:
        assert f["geometry"]["type"] == "LineString" and len(f["geometry"]["coordinates"]) >= 2
        for fact in f["properties"]["facts"]:
            assert fact["source"] and fact["trust"] in ("verified", "listed", "seasonal_or_closed")
    assert any(fact["text"] == "Known gap nearby" for fact in second["facts"])


def test_an_unnamed_corridor_stretch_is_named_after_the_nearest_way():
    from api.segments import _label

    named = _label((1, 9, "East River Esplanade", True, None, None, True, 5, "East 23rd Street"))
    unnamed = _label((1, 89, "unnamed waterfront path", True, None, None, True, 5, "East 23rd Street"))
    assert named.name == "East River Esplanade"
    assert unnamed.name == "waterfront path near East 23rd Street" and unnamed.kind == "corridor"
    assert "catalog #89" in unnamed.source
