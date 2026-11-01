import pytest

from api.nogo import NoGoZone, custom_model, load_zones, resolve, touched

SQUARE = [[[-74.0, 40.70], [-73.99, 40.70], [-73.99, 40.71], [-74.0, 40.71], [-74.0, 40.70]]]
ZONE = NoGoZone(id="test_plaza", name="Test Plaza", aliases=("the plaza",), default=False, reason="r", source="s",
                rings=SQUARE)


def test_shipped_zones_load_and_times_square_is_a_default():
    zones = load_zones()
    ts = next(z for z in zones if z.id == "times_square")
    assert ts.default
    assert ts.source  # every zone says where it came from


def test_resolve_by_name_and_alias_case_insensitively():
    found, unknown = resolve(["test plaza", "THE PLAZA", "Nowhere Park"], zones=[ZONE])
    assert [z.id for z in found] == ["test_plaza"]
    assert unknown == ["Nowhere Park"]


def test_resolve_always_includes_defaults():
    default = NoGoZone(id="always", name="Always", aliases=(), default=True, reason="", source="", rings=SQUARE)
    found, unknown = resolve([], zones=[ZONE, default])
    assert [z.id for z in found] == ["always"]
    assert unknown == []


def test_custom_model_blocks_each_zone_by_area():
    model = custom_model([ZONE])
    assert model["priority"] == [{"if": "in_test_plaza", "multiply_by": "0"}]
    feature = model["areas"]["features"][0]
    assert feature["id"] == "test_plaza"
    assert feature["geometry"] == {"type": "Polygon", "coordinates": SQUARE}


def test_no_zones_means_no_custom_model():
    assert custom_model([]) is None


def test_touched_reports_the_zones_a_route_enters():
    through = [[-74.01, 40.705], [-73.98, 40.705]]
    around = [[-74.01, 40.72], [-73.98, 40.72]]
    assert [z.id for z in touched(through, [ZONE])] == ["test_plaza"]
    assert touched(around, [ZONE]) == []


@pytest.mark.parametrize("bad", ["has space", "1starts_with_digit", "dash-ed"])
def test_zone_ids_must_be_usable_in_a_graphhopper_expression(bad):
    with pytest.raises(ValueError):
        NoGoZone(id=bad, name="x", aliases=(), default=False, reason="", source="", rings=SQUARE)
