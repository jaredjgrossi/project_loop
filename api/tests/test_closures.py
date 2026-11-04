import json
import math

import pytest

from api.closures import PASS_THROUGH_M, Closure, custom_model, length_inside_m, passes_through

LAT = 40.755
M_LAT = 1 / 111_320  # degrees of latitude per meter
M_LON = 1 / (111_320 * math.cos(math.radians(LAT)))


def rect(x0_m, y0_m, x1_m, y1_m, lon=-73.963, lat=LAT):
    """A rectangle given in meters east and north of (lon, lat), as GeoJSON rings."""
    xs = [lon + x0_m * M_LON, lon + x1_m * M_LON]
    ys = [lat + y0_m * M_LAT, lat + y1_m * M_LAT]
    return [[[xs[0], ys[0]], [xs[1], ys[0]], [xs[1], ys[1]], [xs[0], ys[1]], [xs[0], ys[0]]]]


def line(*pts_m, lon=-73.963, lat=LAT):
    return [[lon + x * M_LON, lat + y * M_LAT] for x, y in pts_m]


def closure(rings, in_router=False, cid=1):
    return Closure(id=cid, kind="corridor_gap", name="test link", reason="no path", source="test", trust="listed",
                   rings=rings, in_router=in_router)


# A 200 m long, 20 m wide strip running east-west.
STRIP = rect(0, -10, 200, 10)


def test_length_inside_follows_the_route_along_the_strip():
    assert length_inside_m(line((-50, 0), (250, 0)), STRIP) == pytest.approx(200, abs=6)
    assert length_inside_m(line((50, 0), (120, 0)), STRIP) == pytest.approx(70, abs=6)


def test_length_inside_is_zero_beside_the_strip():
    assert length_inside_m(line((-50, 30), (250, 30)), STRIP) == 0


def test_running_along_a_closure_passes_through_it():
    assert passes_through(line((-50, 0), (250, 0)), closure(STRIP))
    assert passes_through(line((0, 0), (PASS_THROUGH_M + 10, 0)), closure(STRIP))


def test_crossing_a_closure_straight_across_does_not_pass_through_it():
    # A street across the missing link stays open: 20 m inside the strip, under the pass-through length.
    assert not passes_through(line((100, -60), (100, 60)), closure(STRIP))


def test_turning_back_at_the_edge_does_not_pass_through():
    assert not passes_through(line((-80, 0), (-1, 0), (-80, 5)), closure(STRIP))


def test_only_router_closures_go_to_graphhopper_and_their_ids_are_safe():
    assert custom_model([closure(STRIP)]) is None
    m = custom_model([closure(STRIP, in_router=True, cid=7), closure(STRIP, cid=8)])
    assert m["priority"] == [{"if": "in_closure_7", "multiply_by": "0"}]
    assert [f["id"] for f in m["areas"]["features"]] == ["closure_7"]



# --- curated closures (decision 017) -----------------------------------------------------


def curated_feature(**props):
    base = {"name": "A closed park", "reason": "construction", "sources": ["https://example.org/closure"],
            "trust": "listed", "checked_on": "2026-11-02", "review_by": "2027-02-01"}
    return {"type": "Feature", "id": "a_closed_park", "properties": {**base, **props},
            "geometry": {"type": "Polygon", "coordinates": STRIP}}


def test_the_curated_file_parses_and_every_entry_is_complete():
    from api.closures import CURATED_FILE, parse_curated

    entries = parse_curated(json.loads(CURATED_FILE.read_text()))
    assert entries, "the curated file has no closures"
    for e in entries:
        assert e.sources and all(s.startswith("https://") for s in e.sources)
        assert e.checked_on < e.review_by
        assert e.trust == "listed" or (e.trust == "verified" and e.ground_check), e.id


@pytest.mark.parametrize("bad", [{"trust": "probably"}, {"sources": []}, {"sources": ["not a url"]},
                                 {"review_by": None}, {"checked_on": "2027-03-01"}, {"name": ""}])
def test_an_incomplete_curated_entry_is_refused(bad):
    from api.closures import parse_curated

    with pytest.raises(ValueError):
        parse_curated({"features": [curated_feature(**bad)]})


def test_a_curated_entry_needs_a_polygon_and_a_safe_id():
    from api.closures import parse_curated

    point = {**curated_feature(), "geometry": {"type": "Point", "coordinates": [-73.97, 40.72]}}
    with pytest.raises(ValueError):
        parse_curated({"features": [point]})
    with pytest.raises(ValueError):
        parse_curated({"features": [{**curated_feature(), "id": "East River Park"}]})


def test_a_dated_ground_check_lets_an_entry_be_verified():
    from datetime import date

    from api.closures import parse_curated

    (e,) = parse_curated({"features": [curated_feature(trust="verified",
                                                       ground_check={"by": "the reviewer", "on": "2026-11-04"})]})
    assert e.trust == "verified" and e.ground_check == ("the reviewer", date(2026, 11, 4))


@pytest.mark.parametrize("check", [None, {"by": "the reviewer"}, {"by": "", "on": "2026-11-04"},
                                   {"by": "the reviewer", "on": "last week"}])
def test_verified_needs_a_dated_ground_check(check):
    from api.closures import parse_curated

    props = {"trust": "verified"} if check is None else {"trust": "verified", "ground_check": check}
    with pytest.raises(ValueError):
        parse_curated({"features": [curated_feature(**props)]})


def test_a_listed_entry_may_also_record_a_ground_check():
    from api.closures import parse_curated

    (e,) = parse_curated({"features": [curated_feature(ground_check={"by": "the reviewer", "on": "2026-11-04"})]})
    assert e.trust == "listed" and e.ground_check[0] == "the reviewer"
