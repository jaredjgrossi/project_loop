import json
from pathlib import Path

import httpx
import pytest

from api.routing import (
    Route,
    RoutingError,
    RoutingUnavailableError,
    build_round_trip_request,
    parse_route,
    request_round_trip,
    route_to_geojson,
)
from api.units import meters_to_miles

FIXTURES = Path(__file__).parent / "fixtures"
START = (40.741518, -73.986485)  # lat, lon: 11 Madison Ave, Manhattan


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_request_asks_for_a_foot_round_trip_in_meters_with_geojson_points():
    body = build_round_trip_request(*START, distance_m=6437.376, seed=3)
    assert body["profile"] == "foot"
    assert body["algorithm"] == "round_trip"
    assert body["points"] == [[-73.986485, 40.741518]]  # GraphHopper wants lon, lat
    assert body["round_trip.distance"] == pytest.approx(6437.376)
    assert body["round_trip.seed"] == 3
    assert body["points_encoded"] is False


def test_parse_real_graphhopper_response():
    route = parse_route(load("graphhopper_round_trip.json"), seed=0)
    assert route.distance_m == pytest.approx(4881.76)
    assert meters_to_miles(route.distance_m) == pytest.approx(3.03, abs=0.01)
    assert route.coordinates[0] == route.coordinates[-1]  # it is a loop
    assert all(len(c) == 2 for c in route.coordinates)  # lon, lat only


def test_parse_error_response_names_the_problem():
    # A real error body: a start point outside the map.
    with pytest.raises(RoutingError, match="out of bounds"):
        parse_route(load("graphhopper_error_point_not_found.json"), seed=0)


def test_geojson_has_route_and_start_with_the_miss_spelled_out():
    route = parse_route(load("graphhopper_round_trip.json"), seed=0)
    fc = route_to_geojson(route, start_lat=START[0], start_lon=START[1], start_label="11 MADISON AVENUE", requested_miles=4.0)
    assert fc["type"] == "FeatureCollection"
    line, start = fc["features"]
    assert line["geometry"]["type"] == "LineString"
    assert line["properties"]["requested_miles"] == 4.0
    assert line["properties"]["actual_miles"] == pytest.approx(3.03, abs=0.01)
    assert line["properties"]["percent_off"] == pytest.approx(-24.2, abs=0.2)
    assert start["geometry"] == {"type": "Point", "coordinates": [-73.986485, 40.741518]}
    assert start["properties"]["label"] == "11 MADISON AVENUE"


def test_request_round_trip_posts_to_graphhopper_and_returns_a_route():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=load("graphhopper_round_trip.json"))

    route = request_round_trip(*START, distance_m=6437.376, seed=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert isinstance(route, Route)
    assert seen[0].method == "POST" and seen[0].url.path == "/route"
    assert json.loads(seen[0].content)["algorithm"] == "round_trip"


def test_graphhopper_400_surfaces_its_message():
    def handler(request):
        return httpx.Response(400, json=load("graphhopper_error_point_not_found.json"))

    with pytest.raises(RoutingError, match="out of bounds"):
        request_round_trip(0, 0, 6437, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_graphhopper_down_says_how_to_start_it():
    def boom(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(RoutingUnavailableError, match="docker compose up"):
        request_round_trip(*START, distance_m=6437, client=httpx.Client(transport=httpx.MockTransport(boom)))


def test_shape_fields_are_added_to_the_route_properties():
    route = parse_route(load("graphhopper_round_trip.json"), seed=0)
    shape = {"distance_miles": 3.03, "turns": 11, "turns_per_mile": 3.6}
    fc = route_to_geojson(route, START[0], START[1], "11 MADISON AVENUE", 4.0, shape)
    props = fc["features"][0]["properties"]
    assert props["turns"] == 11 and props["turns_per_mile"] == 3.6
    assert "distance_miles" not in props  # actual_miles already carries the routed distance


# --- routing through chosen waypoints (used by the rectangle generator) ------------

from api.routing import build_waypoint_request, request_route  # noqa: E402


def test_waypoint_request_lists_points_in_order_as_lon_lat():
    body = build_waypoint_request([(40.74, -73.98), (40.75, -73.97), (40.74, -73.98)])
    assert body["points"] == [[-73.98, 40.74], [-73.97, 40.75], [-73.98, 40.74]]
    assert body["profile"] == "foot"
    assert "algorithm" not in body  # a plain multi-point route, not a round trip
    assert body["points_encoded"] is False


def test_request_route_returns_the_routed_path():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=load("graphhopper_round_trip.json"))

    route = request_route([START, (40.75, -73.97), START], client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert route.distance_m == pytest.approx(4881.76)
    assert len(json.loads(seen[0].content)["points"]) == 3


def test_request_route_needs_at_least_two_points():
    with pytest.raises(ValueError):
        request_route([START])


def test_request_route_reports_graphhopper_errors():
    def handler(request):
        return httpx.Response(400, json=load("graphhopper_error_point_not_found.json"))

    with pytest.raises(RoutingError, match="out of bounds"):
        request_route([START, (0, 0)], client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_custom_model_is_sent_only_when_given():
    model = {"priority": [{"if": "in_x", "multiply_by": "0"}], "areas": {"type": "FeatureCollection", "features": []}}
    assert "custom_model" not in build_waypoint_request([(40.7, -73.9), (40.71, -73.9)])
    assert build_waypoint_request([(40.7, -73.9), (40.71, -73.9)], custom_model=model)["custom_model"] == model
    assert build_round_trip_request(40.7, -73.9, 5000, custom_model=model)["custom_model"] == model


def test_requests_ask_for_elevation_and_routes_keep_it():
    assert build_waypoint_request([(40.7, -73.9), (40.71, -73.9)])["elevation"] is True
    assert build_round_trip_request(40.7, -73.9, 5000)["elevation"] is True
    with_ele = {"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": [[-73.9, 40.7, 12.5], [-73.9, 40.71, 13.0]]}}]}
    r = parse_route(with_ele, seed=0)
    assert r.coordinates == [[-73.9, 40.7], [-73.9, 40.71]] and r.elevation == [12.5, 13.0]
    flat = {"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": [[-73.9, 40.7], [-73.9, 40.71]]}}]}
    assert parse_route(flat, seed=0).elevation is None


def test_requests_ask_for_turn_instructions_and_routes_keep_their_signs_and_points():
    """Decision 054: the Directions list is built from GraphHopper's turn signs, each at a point of the route."""
    assert build_waypoint_request([(40.7, -73.9), (40.71, -73.9)])["instructions"] is True
    assert build_round_trip_request(40.7, -73.9, 5000)["instructions"] is True
    coords = [[-73.9, 40.7], [-73.9, 40.705], [-73.9, 40.71], [-73.89, 40.71]]
    got = {"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": coords}, "instructions": [
        {"sign": 0, "interval": [0, 2], "street_name": "", "distance": 5, "text": "Continue"},
        {"sign": 2, "interval": [2, 3], "street_name": "", "distance": 5, "text": "Turn right"},
        {"sign": 4, "interval": [3, 3], "street_name": "", "distance": 0, "text": "Arrive at destination"}]}]}
    assert parse_route(got, seed=0).instructions == ((0, 0), (2, 2), (4, 3))
    bare = {"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": coords}}]}
    assert parse_route(bare, seed=0).instructions is None  # a stored route, or a router without them
