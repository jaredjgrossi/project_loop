import math

import pytest

from api.segments import Label, merge_stretches, piece_features, stretch_features

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
    assert all(f["properties"]["crowd"]["status"] == "not_scored" for f in feats)  # none passed: never assumed quiet
    first, second = (f["properties"] for f in feats)
    assert first["from_mile"] == 0 and second["to_mile"] == pytest.approx(1000 / 1609.344, abs=0.02)
    assert second["kind"] == "corridor" and second["signals"]["value"] == 0 and second["signals"]["status"] == "measured"
    assert "each time" in second["signals"]["counted"]  # every crossing, not each crosswalk once (decision 020)
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


def test_stretch_composition_is_measured_meters_by_class():
    coords = [[LON0 + x / KX, LAT0] for x in range(0, 1001, 20)]
    labels = [STREET] * 15 + [GREENWAY] * 36
    comps = [{"waterfront": 0.0, "park": 0.0, "path": 0.0, "street": 300.0},
             {"waterfront": 600.0, "park": 0.0, "path": 100.0, "street": 0.0}]
    first, second = (f["properties"]["composition"] for f in stretch_features(coords, labels, step_m=20, compositions=comps))
    assert first["street_m"] == 300 and second["waterfront_m"] == 600 and second["path_m"] == 100
    assert first["status"] == second["status"] == "measured" and second["source"]
    plain = stretch_features(coords, labels, step_m=20)
    assert plain[0]["properties"]["composition"] == {"status": "not_scored"}


def test_piece_features_carry_kind_meters_and_the_stretch_they_sit_in():
    coords = [[LON0 + x / KX, LAT0] for x in range(0, 1001, 20)]
    stretches = stretch_features(coords, [STREET] * 15 + [GREENWAY] * 36, step_m=20)
    pieces = [{"kind": "street", "range": 0, "start_m": 0.0, "end_m": 300.0, "length_m": 300.0,
               "coordinates": coords[:16]},
              {"kind": "waterfront", "range": 1, "start_m": 300.0, "end_m": 900.0, "length_m": 600.0,
               "coordinates": coords[15:46]},
              {"kind": "path", "range": 1, "start_m": 900.0, "end_m": 1000.0, "length_m": 100.0,
               "coordinates": coords[45:]}]
    feats = piece_features(pieces, stretches)
    props = [f["properties"] for f in feats]
    assert [p["feature"] for p in props] == ["piece"] * 3
    assert [(p["kind"], p["length_m"], p["stretch"], p["stretch_name"]) for p in props] == [
        ("street", 300.0, 0, "East 34th Street"), ("waterfront", 600.0, 1, "East River Greenway"),
        ("path", 100.0, 1, "East River Greenway")]
    assert [p["piece"] for p in props] == [0, 1, 2]
    assert props[2]["from_mile"] == 0.56 and props[2]["to_mile"] == 0.62
    assert all(p["status"] == "measured" and p["source"] for p in props)
    assert feats[1]["geometry"] == {"type": "LineString", "coordinates": coords[15:46]}


# ---- a runnable path is never named after the road beside it (UI review: "FDR Drive", "11th Avenue") -----------------

# row: (ord, corridor id, corridor name, verified, park area, park name, by_water, nearest named way id and name,
#       nearest named non-sidewalk path id and name, nearest way of any name: id, highway, footway tag, name)
WATER = (1, None, None, None, None, None, True)


def test_a_waterfront_sample_takes_the_paths_own_name_not_the_roads():
    from api.segments import _label
    lab = _label((*WATER, 7, "FDR Drive", 9, "East River Esplanade", 9, "cycleway", None, "East River Esplanade"))
    assert (lab.kind, lab.name) == ("waterfront", "East River Esplanade") and "w9" in lab.source and lab.trust == "listed"


def test_a_waterfront_sample_with_no_named_path_is_a_waterfront_path_never_the_road():
    from api.segments import _label
    lab = _label((*WATER, 7, "11th Avenue", None, None, 4, "footway", None, None))
    assert (lab.kind, lab.name) == ("waterfront", "waterfront path")


def test_an_unnamed_path_beside_a_road_is_a_path_not_the_road():
    from api.segments import _label
    row = (1, None, None, None, None, None, False, 7, "East 23rd Street", None, None, 4, "cycleway", None, None)
    assert (_label(row).kind, _label(row).name) == ("path", "unnamed path")


def test_a_sidewalk_is_the_roads_stretch_and_keeps_the_roads_name():
    from api.segments import _label
    row = (1, None, None, None, None, None, False, 7, "East 23rd Street", None, None, 4, "footway", "sidewalk", None)
    assert (_label(row).kind, _label(row).name) == ("street", "East 23rd Street")


def test_a_named_path_off_the_catalog_keeps_its_own_name():
    from api.segments import _label
    row = (1, None, None, None, None, None, False, 7, "FDR Drive", 9, "Bobby Wagner Walk", 9, "footway", None, "Bobby Wagner Walk")
    assert (_label(row).kind, _label(row).name) == ("path", "Bobby Wagner Walk")


def test_the_old_nine_field_rows_still_work():
    from api.segments import _label
    assert _label((1, None, None, None, None, None, False, 5, "East 23rd Street")).name == "East 23rd Street"
